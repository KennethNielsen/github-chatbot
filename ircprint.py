
"""A github centered chatbot"""

from __future__ import print_function

import re
import time
from Queue import Queue
from collections import deque

from twisted.words.protocols import irc
from twisted.internet import protocol, reactor

from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor


class Echo(DatagramProtocol):

    def datagramReceived(self, data, addr):
        print("received %r from %s" % (data, addr))
        PELSBOT.send_multiline_msg(data)
        self.transport.write(data, addr)


COMMAND_RE = re.compile('PyExpLabSysBot:? *(.*)', re.IGNORECASE)
PELSBOT = None


class PelsBot(irc.IRCClient):

    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

    def signedOn(self):
        self.join(self.factory.channel)
        print("Signed on as %s." % (self.nickname,))

    def joined(self, channel):
        # init stuff here
        global PELSBOT
        PELSBOT = self
        self.line_queue = Queue()
        self.line_history = deque(maxlen=5)
        print("Joined %s." % (channel,))

        # Make the client known to the github
        reactor.callLater(0.01, self._send_line)

    def privmsg(self, user, channel, msg):
        print("Got message", msg)
        if not msg.startswith("PyExpLabSysBot"):
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
                self.line_queue.put("{}: Unknown command: {}".format(user, command))            
        else:
            self.line_queue.put("{}: I don't understand".format(user))
        #self.msg(self.factory.channel, msg)

    def send_multiline_msg(self, msg, prefix=''):
        print("Should send multiline message")
        print(msg)
        for line in msg.split('\n'):
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
            print("Burst    ", repr(msg))
        else:
            if now - self.line_history[-1] > 1:
                msg = self.line_queue.get()
                print("Throttled", repr(msg))
            else:
                # delay this line until 1 since last
                reactor.callLater(now - self.line_history[-1], self._send_line)
                return

        #msg = "# " + msg
            
        self.say(self.factory.channel, msg)
        self.line_history.append(now)
        reactor.callLater(0.01, self._send_line)

    def say_to_user(self, user, reply):
        """Convinience say to user command"""
        self.line_queue.put(user + ": " + reply)

    def command_hi(self, user, command):
        """The hi command"""
        self.say_to_user(user, "Hi")
                


class PelsBotFactory(protocol.ClientFactory):
    protocol = PelsBot

    def __init__(self, channel, nickname='PyExpLabSysBot'):
        self.channel = channel
        self.nickname = nickname

    def clientConnectionLost(self, connector, reason):
        print("Lost connection (%s), reconnecting." % (reason,))
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print("Could not connect: %s" % (reason,))


        
if __name__ == "__main__":
    reactor.connectTCP('irc.freenode.net', 6667, PelsBotFactory('#sniksnak'))
    reactor.listenUDP(9999, Echo())
    
    try:
        print('before reactor')
        reactor.run()
        print('after reactor')
    except KeyboardInterrupt:
        print('Set stop')
        reactor.stop()
        
