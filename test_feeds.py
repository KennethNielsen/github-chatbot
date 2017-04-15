

from __future__ import print_function

import re
import requests
import socket
from pprint import pprint

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


class ArchiveParser(object):
    """Git archive feed parser"""

    templates = {
        'issue_comment_event': (
            '### {author} {action_description} \x0308issue {issue_id}\x03 ###\n'
            '# {issue_url}\n'
            '# \x02Message\x02:\n'
            '{comment_clipped}\n'
            '####################'
        ),
        'watch_event': (
            '### {author} {action} watching the '
            '\x0312{repo}\x03 repository \x02{emoji}\x03'
        ),
        'issues_event': (
            '### \x0308Issue {issue_id}\x03 ({issue_url}) '
            'was {action} by {author}'
        ),
    }
    extract_info_template = {
        'author': ('actor', 'display_login'),
        'issue_url': ('payload', 'issue', 'html_url'),
        'issue_id': ('payload', 'issue', 'number'),
        'comment': ('payload', 'comment', 'body'),
        'action': ('payload', 'action'),
        'repo': ('repo', 'name'),
    }
    colors = {
        'author': '\x0310',
        'issue_url': '\x0312'
        
    }
    action_colors = {
        'opened': '\x0303{}\x03',
        'closed': '\x0304{}\x03',
    }

    def __init__(self, repo):
        self.repo = repo

    def _extract_info_dict(self, event_dict):
        """Extract information from event dict into flat dict"""
        #pprint(event_dict)
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
        if info_dict['comment'] is not None:
            info_dict['comment_clipped'] = '\n'.join(["# " + l for l in info_dict['comment'].split('\r\n')[:10]])
        return info_dict

    def format_issue_comment_event(self, event):
        """Format an issue comment"""
        info_dict = self._extract_info_dict(event)
        info_dict.update({'action_description': 'commented on'})
        return self.templates['issue_comment_event'].format(**info_dict)

    def format_issue_comment(self, event):
        """Format an issue comment"""
        raise NotImplementedError()

    def format_issues_event(self, event):
        """Format an issue comment"""
        info_dict = self._extract_info_dict(event)
        if info_dict['action'] in self.action_colors:
            info_dict['action'] = self.action_colors[info_dict['action']].format(info_dict['action'])
        return self.templates['issues_event'].format(**info_dict)
        

    def format_watch_event(self, event):
        """Format an watch event"""
        info_dict = self._extract_info_dict(event)
        if event['payload']['action'] == 'started':
            info_dict.update({'emoji': '\o/'})
        else:
            info_dict.update({'emoji': ':('})
        return self.templates['watch_event'].format(**info_dict)

    def format_pull_request_event(self, event):
        """Format an issue comment"""
        raise NotImplementedError()

    def format_pull_request_review_comment_event(self, event):
        """Format an issue comment"""
        raise NotImplementedError()

    def format_gollum_event(self, event):
        """Format an issue comment"""
        raise NotImplementedError()

    def format_push_event(self, event):
        """Format an issue comment"""
        raise NotImplementedError()

    def format_fork_event(self, event):
        """Format an issue comment"""
        raise NotImplementedError()

    def get_archive_events(self):
        """Get the archive events"""
        page = 1
        found = set()
        while True:
            request = "https://api.github.com/repos/{}/events?page={}&per_page=100".format(self.repo, page)
            r = requests.get(request)
            events = r.json()

            # Break if we are not allowed any more pages
            if r.status_code != 200:
                break

            for event in events:
                event_type = event['type']
                if event_type in found:
                    continue
                found.add(event_type)
                format_method_name = "format_" + camel_to_snake(event_type)
                format_method = getattr(self, format_method_name)
                try:
                    formatted = format_method(event)
                except NotImplementedError:
                    print('###\n', event['type'], 'not implemented')
                    continue
                
                print("###\n" + repr(formatted))
                if event['type'] == 'IssuesEvent':
                    send_to_irc(formatted)
                #break
            break
            page += 1


def e(item):
    """Dict status"""
    if isinstance(item, list):
        print("list with {} items".format(len(item)))
    elif isinstance(item, dict):
        print("dict with {} items".format(len(item)))
        pprint(item)




def main(repo):
    """Main function, repo is "owner/reponame" string"""
    achive_parser = ArchiveParser(repo)
    achive_parser.get_archive_events()
    #get_archive_events(repo)


main("SoCo/SoCo")
