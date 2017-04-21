

from __future__ import print_function

from time import sleep
import re
import socket
from pprint import pprint
import json

from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from twisted.logger import textFileLogObserver, globalLogBeginner, Logger

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
        'commit_comment_event': (
            '{author} commented on \x0308commit {commit_id}\x03\n'
            '{comment_url}\n'
            '\x02Message\x02:\n'
            '{comment_clipped}'
        ),
        'fork_event': (
            '{author} forked {repo_name} \\o/'
        ),
        'gollum_event': (
            '{author} {wiki_action} the wiki page \x0312{wiki_url}\x03'
        ),
        'issue_comment_event': (
            '{author} {action_description} \x0308issue {issue_id}\x03\n'
            '{issue_url}\n'
            '\x02Message\x02:\n'
            '{comment_clipped}'
        ),
        'issues_event': (
            '\x0308Issue {issue_id}\x03 ({issue_url}) '
            'was {action} by {author}'
        ),
        'watch_event': (
            '{author} {action} watching the '
            '\x0312{repo}\x03 repository \x02{emoji}\x03'
        ),
        'pull_request_event': (
            '\x0308Pull request {pull_request_id}\x03 ({pull_request_url}) '
            'was {action} by {author}'
        ),
        'pull_request_review_comment_event': (
            '{author} made a review comment on \x0308pull request {pull_request_id}\x03 '
            '({pull_request_url})'
        ),
        'push_event': (
            '{author} pushed {size} commits to {ref} now at \x0308{head}\x03'
        ),
        'requested_issue': (
            '{state} \x0308{type} #{number}\x03 \x02"{title}"\x02 by \x0309{author}\x03{labels} \x0312{html_url}\x03'
        ),
    }
    extract_info_template = {
        'author': ('actor', 'display_login'),
        'issue_url': ('payload', 'issue', 'html_url'),
        'issue_id': ('payload', 'issue', 'number'),
        'pull_request_url': ('payload', 'pull_request', 'html_url'),
        'pull_request_id': ('payload', 'pull_request', 'number'),
        'commit_id': ('payload', 'comment', 'commit_id'),
        'comment_url': ('payload', 'comment', 'html_url'),
        'comment': ('payload', 'comment', 'body'),
        'action': ('payload', 'action'),
        'repo': ('repo', 'name'),
        'size': ('payload', 'size'),
        'ref': ('payload', 'ref'),
        'head': ('payload', 'head'),
    }
    colors = {
        'author': '\x0309',
        'issue_url': '\x0312',
        'pull_request_url': '\x0312',
        'ref': '\x0312',
        
    }
    action_colors = {
        'opened': '\x0303{}\x03',
        'closed': '\x0304{}\x03',
    }

    def __init__(self, repo, reactor=None, chatbot=None):
        self.repo = repo
        _, self.repo_name = repo.split('/')
        self.reactor = reactor
        self.chatbot = chatbot
        self.last_known_id = None

        self.feed_link = "https://api.github.com/repos/{}/events?per_page=100".format(repo)
        self.issue_link = "https://api.github.com/repos/{}/issues/{{}}".format(repo)
        self.agent = None
        if reactor:
            self.agent = Agent(reactor)

    def _extract_info_dict(self, event_dict):
        """Extract information from event dict into flat dict"""
        info_dict = {}
        for info_name, keys in self.extract_info_template.items():
            try:
                value = event_dict
                for key in keys:
                    value = value[key]
                if info_name in self.colors:
                    info_dict[info_name] = self.colors[info_name] + value + '\x03'
                else:
                    info_dict[info_name] = value
            except KeyError:
                info_dict[info_name] = None

        # Strip unicode out of comments
        if info_dict['comment'] is not None:
            info_dict['comment'] = info_dict['comment'].strip().encode('ascii', 'ignore').decode('ascii')

        if info_dict['comment'] is not None:
            info_dict['comment_clipped'] = '\n'.join(["# " + l for l in info_dict['comment'].split('\r\n')[:10]])
        return info_dict

    ### Methods for formatting each of the event types we support

    # https://developer.github.com/v3/activity/events/types/#commitcommentevent
    def format_commit_comment_event(self, event):
        """Format a commit comment event"""
        info_dict = self._extract_info_dict(event)
        return self.templates['commit_comment_event'].format(**info_dict)

    # https://developer.github.com/v3/activity/events/types/#forkevent
    def format_fork_event(self, event):
        """Format a fork event"""
        info_dict = self._extract_info_dict(event)
        info_dict['repo_name'] = self.repo_name
        return self.templates['fork_event'].format(**info_dict)
    
    # https://developer.github.com/v3/activity/events/types/#gollumevent
    def format_gollum_event(self, event):
        """Format an gollum comment"""
        info_dict = self._extract_info_dict(event)
        page_updates = []
        for page in event['payload']['pages']:
            info_dict['wiki_action'] = page['action']
            info_dict['wiki_url'] = page['html_url']
            page_updates.append(
                self.templates['gollum_event'].format(**info_dict)
            )
        return '\n'.join(page_updates)
    
    # https://developer.github.com/v3/activity/events/types/#issuecommentevent
    def format_issue_comment_event(self, event):
        """Format an issue comment"""
        info_dict = self._extract_info_dict(event)
        info_dict.update({'action_description': 'commented on'})
        return self.templates['issue_comment_event'].format(**info_dict)

    # https://developer.github.com/v3/activity/events/types/#issuesevent
    def format_issues_event(self, event):
        """Format an issue comment"""
        info_dict = self._extract_info_dict(event)
        if info_dict['action'] in self.action_colors:
            info_dict['action'] = self.action_colors[info_dict['action']].format(info_dict['action'])
        return self.templates['issues_event'].format(**info_dict)

    # https://developer.github.com/v3/activity/events/types/#pullrequestevent
    def format_pull_request_event(self, event):
        """Format a pull request event"""
        info_dict = self._extract_info_dict(event)
        if info_dict['action'] in self.action_colors:
            info_dict['action'] = self.action_colors[info_dict['action']].format(info_dict['action'])
        return self.templates['pull_request_event'].format(**info_dict)

    # https://developer.github.com/v3/activity/events/types/#pullrequestreviewcommentevent
    def format_pull_request_review_comment_event(self, event):
        """Format a pull request review comment event"""
        info_dict = self._extract_info_dict(event)
        info_dict.update({'action_description': 'commented on'})
        return self.templates['pull_request_review_comment_event'].format(**info_dict)

    # https://developer.github.com/v3/activity/events/types/#pushevent
    def format_push_event(self, event):
        """Format a push comment"""
        info_dict = self._extract_info_dict(event)
        return self.templates['push_event'].format(**info_dict)

    # https://developer.github.com/v3/activity/events/types/#watchevent
    def format_watch_event(self, event):
        """Format an watch event"""
        info_dict = self._extract_info_dict(event)
        if event['payload']['action'] == 'started':
            info_dict.update({'emoji': '\o/'})
        else:
            info_dict.update({'emoji': ':('})
        return self.templates['watch_event'].format(**info_dict)

    ## High level methods
    def watch_for_events(self, first_call=False, etag=None):
        """Main method for continuously looking for events"""
        log.debug("Watch for events")
        headers = {'User-Agent': ['Github chat bot']}
        if etag is not None:
            headers.update({'If-None-Match': etag})
        d = self.agent.request(
            'GET',
            self.feed_link,
            Headers(headers),
            None,
        )
        d.addCallback(self.request_callback)

    def request_callback(self, response):
        """Callback for when the feed has been retrived"""
        log.debug("request callback")

        if response.code not in (304, 200):
            log.debug("error getting the feed, try again in 5 min")
            self.reactor.callLater(300, self.watch_for_events, False, etag)
            return

        headers = dict(response.headers.getAllRawHeaders())
        etag = headers['ETag']

        # If not modified
        if response.code == 304:
            log.debug("no new content (304), try again in 60 s")
            self.reactor.callLater(60, self.watch_for_events, False, etag)
            return

        # Set body callback
        polling_interval = int(headers['X-Poll-Interval'][0])
        d = readBody(response)
        d.addCallback(self.body_received_callback, polling_interval, etag)
        

    def body_received_callback(self, body, polling_interval, etag):
        """Body received callback"""
        log.debug("Got body")
        events = json.loads(body)

        # This is the first time ever
        if self.last_known_id is None:
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
        self.reactor.callLater(polling_interval, self.watch_for_events, False,
                               etag)

    def act_on_event(self, event):
        """Act on an event"""
        self.last_known_id = event['id']

        event_type = event['type']
        format_method_name = "format_" + camel_to_snake(event_type)
        try:
            format_method = getattr(self, format_method_name)
            formatted_msg = format_method(event)
        except AttributeError:
            formatted_msg = "I don't know how to handle event type {}. Tell "\
                            "TLE to fix me.".format(event_type)

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
        
    def issue_request_callback(self, response, issue_number):
        """Callback for when the feed has been retrived"""
        log.debug("request callback")

        headers = dict(response.headers.getAllRawHeaders())
        
        if response.code != 200:
            log.debug("error getting the issue {issue} {code}", issue=issue_number, code=response.code)
            return

        d = readBody(response)
        d.addCallback(self.issue_body_received_callback)

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
        formatted_msg = self.templates['requested_issue'].format(**info)
        self.chatbot.send_multiline_msg(formatted_msg)
        
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
