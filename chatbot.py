
"""A github centered chatbot"""

from __future__ import print_function

import re
import sys
import time
from Queue import Queue
from collections import deque

from twisted.words.protocols import irc
from twisted.internet import protocol, reactor
from twisted.logger import textFileLogObserver, globalLogBeginner, Logger
globalLogBeginner.beginLoggingTo([textFileLogObserver(sys.stdout)])

from github_events import GithubArchiveEventsParser

log = Logger(namespace="CHATBOT")
log.info("Started")


class PelsBot(irc.IRCClient):

    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

    def signedOn(self):
        self.join(self.factory.channel)
        log.info("Signed on as {nick}", nick=self.nickname)

    def joined(self, channel):
        # init stuff here
        self.line_queue = Queue()
        self.line_history = deque(maxlen=5)
        log.info("Joined {channel}", channel=channel)

        # Make the client known to the github
        self.event_parser = GithubArchiveEventsParser(self.factory.repo, reactor, self)
        self.event_parser.watch_for_events(first_call=True)
        self._send_line()

    def privmsg(self, user, channel, msg):
        """Recieved msg"""
        log.info("Got message {msg}", msg=msg)
        if not msg.startswith(self.factory.nickname):
            self.look_for_key_words(msg)
            return

        user = user.split("!", 1)[0]
        command_match = COMMAND_RE.match(msg)
        if command_match:
            command = command_match.group(1)
            command_base = command.split(" ", 1)[0]
            command_method = getattr(self, "command_" + command_base.lower(), None)
            if command_method:
                command_method(user, command)
            else:
                self.line_queue.put("{}: Unknown command: '{}' try 'help'".format(user, command))            
        else:
            self.line_queue.put("{}: I don't understand".format(user))
        #self.msg(self.factory.channel, msg)

    def look_for_key_words(self, msg):
        """Look for keywords in a msg"""
        match = ISS_RE.match(msg)
        if match:
            issue_number = int(match.group(1))
            log.debug("Found issue number {issue}", issue=issue_number)
            self.event_parser.show_issue(issue_number)

    def send_multiline_msg(self, msg, prefix=''):
        log.debug("Should send multiline message:")
        for line in msg.split('\n'):
            log.debug("# {prefix}{line}", prefix=prefix, line=line)
            self.line_queue.put(prefix + line)

    def _send_line(self):
        # Nothing to send
        if self.line_queue.qsize() == 0:
            reactor.callLater(0.1, self._send_line)
            return

        now = time.time()
        if len(self.line_history) < 5 or now - self.line_history[0] > 10:
            # Burst allowed
            msg = self.line_queue.get()
            log.debug("Burst    {msg}", msg=repr(msg))
        else:
            if now - self.line_history[-1] > 1:
                msg = self.line_queue.get()
                log.debug("Throttled{msg}", msg=repr(msg))
            else:
                # delay this line until 1 since last
                reactor.callLater(now - self.line_history[-1], self._send_line)
                return

        self.say(self.factory.channel, msg)
        self.line_history.append(now)
        reactor.callLater(0.01, self._send_line)

    def say_to_user(self, user, reply):
        """Convinience say to user command"""
        self.line_queue.put(user + ": " + reply)

    def command_hi(self, user, command):
        """The hi command"""
        self.say_to_user(user, "Hi")

    def command_help(self, user, command):
        """The help command"""
        msg = (
            'I\'m the friendly bot for {}. '
            'I will keep you updated on repository events and I understand the commands: hi, help'
        ).format(self.factory.repo)
        self.say_to_user(user, msg)
                


class PelsBotFactory(protocol.ClientFactory):
    protocol = PelsBot

    def __init__(self, channel, repo, nickname='GithubBot'):
        self.channel = channel
        self.repo = repo
        self.nickname = nickname

    def clientConnectionLost(self, connector, reason):
        log.debug("Lost connection {reason}, reconnecting", reason=reason)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        log.debug("Could not connect: {reason}", reason=reason)

        
if __name__ == "__main__":
    _, bot_name, channel, repo = sys.argv
    log.debug(str(sys.argv))
    COMMAND_RE = re.compile('{}:? *(.*)'.format(bot_name), re.IGNORECASE)
    ISS_RE = re.compile('.*#(\d+).*', re.DOTALL)

    reactor.connectTCP('irc.freenode.net', 6667, PelsBotFactory(channel, repo, bot_name))
    
    try:
        log.info('before reactor')
        reactor.run()
        log.info('after reactor')
    except KeyboardInterrupt:
        log.debug('Ctrl-C stop')
        reactor.stop()
        
