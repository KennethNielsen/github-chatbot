
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

    template = (
        '### \x0308{author}\x03 {action_description} \x0308{subject_id}\x03 ###\n'
        '# \x0312URL: {url}\x03\n'
        '# \x02Message\x02:\n'
        '{message}\n'
        '####################'
    )

    def __init__(self, repo):
        self.repo = repo

    def format_issue_comment_event(self, event):
        """Format an issue comment"""
        pprint(event)
        content = {'action_description': 'commented on'}
        content['author'] = event['actor']['display_login']
        payload = event['payload']
        content['url'] = payload['issue']['html_url']
        content['subject_id'] = 'issue {}'.format(payload['issue']['number'])
        comment = payload['comment']['body']
        content['message'] = '\n'.join(["# " + l for l in comment.split('\r\n')[:10]])
        
        output = self.template.format(**content)
        return output

    def format_issue_comment(self, event):
        """Format an issue comment"""
        return event['type']

    def format_issues_event(self, event):
        """Format an issue comment"""
        return event['type']

    def format_watch_event(self, event):
        """Format an issue comment"""
        return event['type']

    def format_pull_request_event(self, event):
        """Format an issue comment"""
        return event['type']

    def format_pull_request_review_comment_event(self, event):
        """Format an issue comment"""
        return event['type']

    def format_gollum_event(self, event):
        """Format an issue comment"""
        return event['type']

    def format_push_event(self, event):
        """Format an issue comment"""
        return event['type']

    def format_fork_event(self, event):
        """Format an issue comment"""
        return event['type']

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
                formatted = format_method(event)
                
                print("###\n" + formatted)
                send_to_irc(formatted)
                break
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
