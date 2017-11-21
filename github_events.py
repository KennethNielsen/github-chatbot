

from __future__ import print_function

from time import sleep
import re
import socket
from pprint import pprint, pformat
import json

from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from twisted.logger import textFileLogObserver, globalLogBeginner, Logger
from twisted.words.protocols.irc import assembleFormattedText
from twisted.words.protocols.irc import attributes as A

# Color alias
fg = A.fg

log = Logger(namespace="EVENTS")
log.info("events")


FIRST_CAP_RE = re.compile('(.)([A-Z][a-z]+)')
ALL_CAP_RE = re.compile('([a-z0-9])([A-Z])')
def camel_to_snake(string):
    """Turn camel case into snake case"""
    string = FIRST_CAP_RE.sub(r'\1_\2', string)
    return ALL_CAP_RE.sub(r'\1_\2', string).lower()


SOCK = socket.socket(socket.AF_INET, # Internet
                     socket.SOCK_DGRAM) # UDP
def send_to_irc(text):
    SOCK.sendto(text, ('localhost', 9999))


class GithubArchiveEventsParser(object):
    """Github archive feed parser"""

    templates = {
        'commit_comment_event': [
            fg.lightGreen['{author}'], ' commented on ', fg.yellow['commit {commit_id}']
        ],
        'fork_event': [
            fg.lightGreen['{author}'], ' forked {repo_name} ', A.bold['\\o/']
        ],
        'gollum_event': [
            '{all_gollum_events}'
        ],
        'gollum_event_component': [
            fg.lightGreen['{author}'], ' {wiki_action} the wiki page ',
            fg.lightBlue['{wiki_url}']
        ],
        'issue_comment_event': [
            fg.lightGreen['{author}'], ' commented on ',
            fg.yellow['issue {issue_id} '], A.bold['"{issue_title}" '],
            fg.lightBlue['{comment_url}'],
        ],
        'issues_event': [
            fg.yellow['Issue {issue_id} '], A.bold['"{issue_title}"'], ' (',
            fg.lightBlue['{issue_url}'], ') was ', '{action}', ' by ',
            fg.lightGreen['{author}']
        ],
        'watch_event': [
            fg.lightGreen['{author}'], ' {action} watching the ',
            fg.lightBlue['{repo}'], ' repository ', A.bold['{emoji}']
        ],
        'pull_request_event': [
            fg.yellow['Pull request {pull_request_id}'],
            A.bold[' "{pull_request_title}"'], ' (', fg.lightBlue['{pull_request_url}'],
            ') was ', '{action}', ' by ', fg.lightGreen['{author}']
        ],
        'pull_request_review_comment_event': [
            fg.lightGreen['{author}'], ' made a review comment on ',
            fg.yellow['pull request {pull_request_id}'],
            A.bold[' "{pull_request_title}"'], ' (', fg.lightBlue['{comment_url}'], ')'
        ],
        'push_event': [
            fg.lightGreen['{author}'], ' pushed {size} commits to ',
            fg.lightBlue['{ref}'], ', now at ', fg.yellow['{head}']
        ],
        'requested_issue': [
            '{state} ', fg.yellow['{type} #{number}'], A.bold[' "{title}" '], 'by ',
            fg.lightGreen['{author}'], '{labels} ', fg.lightBlue['{html_url}']
        ],
        'release_event': [
            ' -=# ', fg.lightGreen['{author}'], ' just release version ',
            fg.yellow['{release_name}'], A.bold[' \o/\o/\o/' ], ' #=-\n',
            ' -=# ', fg.lightBlue['{release_url}'], ' #=-',
        ],
        'create_event': [
            fg.lightGreen['{author}'], ' created ', fg.yellow['{ref_type} {ref}']
        ],
        'default_event': [
            fg.lightRed['##### WARNING. '],
            'Unkown event of type: \"{event_type}\". Ask TLE to fix me.',
        ],

    }
    extract_info_template = {
        'author': ('actor', 'display_login'),
        'issue_url': ('payload', 'issue', 'html_url'),
        'issue_id': ('payload', 'issue', 'number'),
        'issue_title': ('payload', 'issue', 'title'),
        'pull_request_url': ('payload', 'pull_request', 'html_url'),
        'pull_request_id': ('payload', 'pull_request', 'number'),
        'pull_request_title': ('payload', 'pull_request', 'title'),
        'commit_id': ('payload', 'comment', 'commit_id'),
        'comment_url': ('payload', 'comment', 'html_url'),
        'comment': ('payload', 'comment', 'body'),
        'action': ('payload', 'action'),
        'repo': ('repo', 'name'),
        'size': ('payload', 'size'),
        'ref': ('payload', 'ref'),
        'ref_type': ('payload', 'ref_type'),
        'head': ('payload', 'head'),
        'release_name': ('payload', 'release', 'name'),
        'release_url': ('payload', 'release', 'html_url'),
        'event_type': ('type',)
    }
    action_colors = {
        'opened': 'green',
        'closed': 'lightRed',
    }

    def __init__(self, repo, reactor=None, chatbot=None):
        self.repo = repo
        _, self.repo_name = repo.split('/')
        self.reactor = reactor
        self.chatbot = chatbot
        self.last_known_id = None

        self.feed_link = "https://api.github.com/repos/{}/events?per_page=100".format(repo)
        self.issue_link = "https://api.github.com/repos/{}/issues/{{}}".format(repo)
        self.headers = {'User-Agent': ['Github chat bot']}
        self.agent = None
        if reactor:
            self.agent = Agent(reactor)

    def _extract_info_dict(self, event_dict):
        """Extract information from event dict into flat dict"""
        info_dict = {'repo_name': self.repo_name}
        for info_name, keys in self.extract_info_template.items():
            try:
                value = event_dict
                for key in keys:
                    value = value[key]
                info_dict[info_name] = value
            except KeyError:
                info_dict[info_name] = None

        # Strip unicode out of comments and titles
        for item_name in ('comment', 'issue_title', 'pull_request_title'):
            if info_dict[item_name] is not None:
                info_dict[item_name] =\
                    info_dict[item_name].strip().encode('ascii', 'ignore').decode('ascii')

        if info_dict['comment'] is not None:
            info_dict['comment_clipped'] = '\n'.join(
                ["# " + l for l in info_dict['comment'].split('\r\n')[:10]]
            )
        return info_dict

    ### Methods for customizing information before formatting it into templates
    
    def customize_gollum_event(self, event, info_dict):
        """Customize the gollum event data"""
        page_updates = []
        for page in event['payload']['pages']:
            info_dict['wiki_action'] = page['action']
            info_dict['wiki_url'] = page['html_url']
            template = assembleFormattedText(A.normal[self.templates['gollum_event_component']])
            page_update_string = template.format(**info_dict)
            page_updates.append(page_update_string)
        info_dict['all_gollum_events'] = '\n'.join(page_updates)

    def customize_watch_event(self, event, info_dict):
        """Customize the watch event data"""
        if event['payload']['action'] == 'started':
            info_dict.update({'emoji': '\o/'})
        else:
            info_dict.update({'emoji': ':('})

    def handle_action_colors(self, info_dict, color_template):
        """Change the color templates to accommodate action colors"""
        for index in range(len(color_template)):
            if color_template[index] == '{action}':
                action = info_dict['action']
                color_factory = getattr(fg, self.action_colors[action])
                color_template[index] = color_factory['{action}']

    ## High level methods
    def watch_for_events(self, etag=None):
        """Main method for continuously looking for events"""
        log.debug("Watch for events")
        headers = {'User-Agent': ['Github chat bot']}
        if etag is not None:
            self.headers.update({'If-None-Match': etag})
        d = self.agent.request(
            'GET',
            self.feed_link,
            Headers(self.headers),
            None,
        )
        d.addCallback(self.request_callback)
        d.addErrback(self.request_errback)

    def request_errback(self, failure, *args, **kwargs):
        """Error back for get internet page request"""
        log.debug("Request error back, grumble!")
        #log.error('', failure)
        self.reactor.callLater(300, self.watch_for_events)

    def request_callback(self, response):
        """Callback for when the feed has been retrived"""
        log.debug("request callback")

        if response.code not in (304, 200):
            log.debug("error getting the feed, try again in 5 min")
            self.reactor.callLater(300, self.watch_for_events)
            return

        headers = dict(response.headers.getAllRawHeaders())
        etag = headers['ETag']

        # If not modified
        if response.code == 304:
            log.debug("no new content (304), try again in 60 s")
            self.reactor.callLater(60, self.watch_for_events, etag)
            return

        # Set body callback
        polling_interval = int(headers['X-Poll-Interval'][0])
        d = readBody(response)
        d.addCallback(self.body_received_callback, polling_interval, etag)
        d.addErrback(self.body_received_errback)

    def body_received_callback(self, body, polling_interval, etag):
        """Body received callback"""
        log.debug("Got body")
        events = json.loads(body)

        # This is the first time ever
        if self.last_known_id is None:
            #know_types = set()
            #for event in events:
            #    if event['type'] not in know_types:
            #        self.act_on_event(event)
            #        know_types.add(event['type'])
            self.act_on_event(events[0])
        else:
            seen_last_known = False
            for event in reversed(events):
                if seen_last_known:
                    self.act_on_event(event)
                elif event['id'] == self.last_known_id:
                    seen_last_known = True
            
        log.debug("reponse parsed, call again later after appropriate polling "
                  "intervall {pol_int}", pol_int=polling_interval)
        self.reactor.callLater(polling_interval, self.watch_for_events, etag)

    def body_received_errback(self, failure, *args, **kwargs):
        """Body received error back"""
        log.debug("Body received error back. THIS SHOULD NOT HAPPEN")
        #log.err(failure)

    def act_on_event(self, event):
        """Act on an event"""
        self.last_known_id = event['id']

        # Form the event name, extract relevant information into the info_dict, fetch and
        # possibly customize color template
        event_type = camel_to_snake(event['type'])
        #with open(event_type, 'w') as file_:
        #    file_.write(pformat(event))
        info_dict = self._extract_info_dict(event)
        color_template = self.templates[event_type]
        self.handle_action_colors(info_dict, color_template)

        # Check if this type needs custom modification
        customize_method = getattr(self, 'customize_' + event_type, None)
        if customize_method is not None:
            customize_method(event, info_dict)  # modifies info_dict

        # Assemble the color template and format information into it
        template = assembleFormattedText(A.normal[color_template])
        formatted_msg = template.format(**info_dict)
        self.chatbot.send_multiline_msg(formatted_msg)
        
    def show_issue(self, issue_number, in_detail=False):
        """Get information about an issue"""
        log.debug("Show issue {issue}", issue=issue_number)
        headers = {'User-Agent': ['dGithub chat bot']}
        d = self.agent.request(
            'GET',
            self.issue_link.format(issue_number),
            Headers(headers),
            None,
        )
        d.addCallback(self.issue_request_callback, issue_number)
        d.addErrback(self.issue_request_errback)
        
    def issue_request_callback(self, response, issue_number):
        """Callback for when the feed has been retrived"""
        log.debug("request callback")

        headers = dict(response.headers.getAllRawHeaders())
        
        if response.code != 200:
            log.debug("error getting the issue {issue} {code}", issue=issue_number, code=response.code)
            message = "Fetching issue information fails right now, try again later"
            self.chatbot.send_multiline_msg(message)
            return

        d = readBody(response)
        d.addCallback(self.issue_body_received_callback)
        d.addErrback(self.issue_request_errback)

    def issue_body_received_callback(self, body):
        """Body received callback"""
        log.debug("Got body")
        info = json.loads(body)
        if info['labels']:
            label_names = (label['name'] for label in info['labels'])
            info['labels'] = ' ({})'.format(', '.join(label_names))
        else:
            info['labels'] = ''
        info['type'] = "pull request" if 'pull_request' in info else "issue"
        info['author'] = info['user']['login']
        for state, color in (("open", "\x0303"), ("closed", "\x0304")):
            if state == info['state']:
                info['state'] = color + info['state'].title() + '\x03'
                break
        else:
            info['state'] = info['state'].title()
        color_template = assembleFormattedText(
            A.normal[self.templates['requested_issue']]
        )
        formatted_msg = color_template.format(**info)
        
        self.chatbot.send_multiline_msg(formatted_msg)

    def issue_request_errback(self, failure, *args, **kwargs):
        """Error back for when an issue request fails"""
        log.debug("Issue request error back")
        #log.err(failure)
        message = "Fetching issue information fails right now, try again later"
        self.chatbot.send_multiline_msg(message)
        
    ## Test archive parsing
    def test_get_archive_events(self):
        """Get the archive events"""
        import requests
        found = set()
        while True:
            request = "https://api.github.com/repos/{}/events?per_page=100".format(self.repo)
            r = requests.get(request)
            events = r.json()

            # Break if we are not allowed any more pages
            if r.status_code != 200:
                print("no more allowed")
                break

            for event in events:
                event_type = event['type']
                #if event_type in found:
                #    continue
                print("##############")
                print("Event type", event_type)
                found.add(event_type)
                format_method_name = "format_" + camel_to_snake(event_type)
                format_method = getattr(self, format_method_name)
                #try:
                formatted = format_method(event)
                #except NotImplementedError:
                #    print(event['type'], 'not implemented')
                #    continue
                
                print(repr(formatted))
                #if event_type == 'GollumEvent':
                #    send_to_irc(formatted)
                #    sleep(2)
                #break
        print(found)



def main(repo):
    """Main function, repo is "owner/reponame" string"""
    achive_parser = GithubArchiveEventsParser(repo)
    achive_parser.test_get_archive_events()
    #get_archive_events(repo)

def main_twisted(repo):
    import sys
    from twisted.internet import reactor
    from twisted.logger import textFileLogObserver, globalLogBeginner, Logger
    globalLogBeginner.beginLoggingTo([textFileLogObserver(sys.stdout)])
    archive_parser = GithubArchiveEventsParser(repo, reactor=reactor)
    #reactor.callWhenRunning(archive_parser.watch_for_events)
    reactor.callWhenRunning(archive_parser.show_issue, 493)
    #for n in range(1, 10):
    #    reactor.callWhenRunning(archive_parser.show_issue, n)
    reactor.run()


if __name__ == '__main__':
    #main("SoCo/SoCo")
    main_twisted("SoCo/SoCo")
