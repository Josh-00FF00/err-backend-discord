from typing import Any, List

from errbot.backends.base import Person, Message, Room, RoomOccupant, Presence, \
    ONLINE, OFFLINE, AWAY, DND, Identifier
from errbot.core import ErrBot
import logging
import sys
import asyncio

log = logging.getLogger(__name__)

try:
    import discord
except ImportError:
    log.exception("Could not start the Discord back-end")
    log.fatal(
        "You need to install the Discord API in order to use the Discord backend.\n"
        "You can do `pip install -r requirements.txt` to install it"
    )
    sys.exit(1)

# Discord message size limit.
DISCORD_MESSAGE_SIZE_LIMIT = 2000

COLORS = {
    'red': 0xFF0000,
    'green': 0x008000,
    'yellow': 0xFFA500,
    'blue': 0x0000FF,
    'white': 0xFFFFFF,
    'cyan': 0x00FFFF
}  # Discord doesn't know its colors


class DiscordPerson(Person):

    def __init__(self, user: discord.User):
        self.user = user

    @property
    def person(self) -> str:
        return self.user.discriminator

    @property
    def aclattr(self) -> str:
        return self.user.id

    @property
    def nick(self) -> str:
        return self.user.name

    @property
    def fullname(self) -> str:
        return self.user.name

    @property
    def client(self) -> str:
        return self.user.id

    def __eq__(self, other):
        return isinstance(other, DiscordPerson) and other.person == self.person

    async def trigger_typing(self):
        await self.user.trigger_typing()

    async def send(self, content: str = None, embed=None):
        await self.user.send(content=content, embed=embed)


class DiscordRoom(Room):
    def invite(self, *args) -> None:
        log.error('Not implemented')

    @property
    def joined(self) -> bool:
        log.error('Not implemented')
        return True

    def leave(self, reason: str = None) -> None:
        log.error('Not implemented')

    def create(self) -> None:
        log.error('Not implemented')

    def destroy(self) -> None:
        log.error('Not implemented')

    def join(self, username: str = None, password: str = None) -> None:
        log.error('Not implemented')

    @property
    def topic(self) -> str:
        log.error('Not implemented')
        return ''

    @property
    def occupants(self) -> List[RoomOccupant]:
        log.error('Not implemented')
        return []

    @property
    def exists(self) -> bool:
        log.error('Not implemented')
        return True

    def __init__(self, name, channel: discord.TextChannel = None):
        self.name = name
        self.channel = channel

    async def trigger_typing(self):
        await self.channel.trigger_typing()

    async def send(self, content: str = None, embed=None):
        await self.channel.send(content=content, embed=embed)

    def __str__(self):
        return '#' + self.name

    def __eq__(self, other):
        return other.name == self.name


class DiscordRoomOccupant(RoomOccupant):

    def __init__(self, member: discord.Member, channel: discord.TextChannel):
        self._channel = channel
        self.member = member

    @property
    def person(self) -> discord.Member:
        return self.member

    @property
    def room(self) -> discord.TextChannel:
        return self._channel

    def __eq__(self, other):
        return isinstance(other, DiscordRoomOccupant) and str(other) == str(self)

    def __str__(self):
        return super().__str__() + '@' + self._channel.name


class DiscordBackend(ErrBot):
    """
    This is the Discord backend for Errbot.
    """

    def build_identifier(self, text_representation: str) -> Identifier:
        raise NotImplementedError()

    def __init__(self, config):
        super().__init__(config)
        identity = config.BOT_IDENTITY

        self.token = identity.get('token', None)
        self.rooms_to_join = config.CHATROOM_PRESENCE

        if not self.token:
            log.fatal('You need to set a token entry in the BOT_IDENTITY setting of your configuration.')
            sys.exit(1)
        self.bot_identifier = None

        self.client = discord.Client()
        self.on_ready = self.client.event(self.on_ready)
        self.on_message = self.client.event(self.on_message)
        self.on_member_update = self.client.event(self.on_member_update)

    async def on_ready(self):
        log.debug('Logged in as %s, %s' % (self.client.user.name, self.client.user.id))
        if self.bot_identifier is None:
            self.bot_identifier = DiscordPerson(self.client.user)

        for channel in self.client.get_all_channels():
            log.debug('Found channel: %s', channel)

    async def on_message(self, msg: discord.Message):
        err_msg = Message(msg.content)

        if isinstance(msg.channel, discord.abc.PrivateChannel):
            err_msg.frm = DiscordPerson(msg.author)
            err_msg.to = self.bot_identifier
        else:
            err_msg.to = DiscordRoom(msg.channel)
            err_msg.frm = DiscordRoomOccupant(msg.author, msg.channel)

        log.debug('Received message %s' % msg)
        self.callback_message(err_msg)
        if msg.mentions:
            self.callback_mention(err_msg,
                                  [DiscordRoomOccupant(mention, msg.channel)
                                   for mention in msg.mentions])

    def is_from_self(self, msg: Message) -> bool:
        return msg.frm == self.bot_identifier

    async def on_member_update(self, before, after):
        if before.status != after.status:
            person = DiscordPerson(after)

            log.debug('Person %s changed status to %s from %s' % (person, after.status, before.status))

            if after.status == discord.Status.online:
                self.callback_presence(Presence(person, ONLINE))
            elif after.status == discord.Status.offline:
                self.callback_presence(Presence(person, OFFLINE))
            elif after.status == discord.Status.idle:
                self.callback_presence(Presence(person, AWAY))
            elif after.status == discord.Status.dnd:
                self.callback_presence(Presence(person, DND))
        else:
            log.debug('Unrecognised member update, ignoring...')

    def query_room(self, room):
        return self.build_identifier(room)  # backward compatibility.

    def send_message(self, msg: Message):
        log.debug('Send:\n%s\nto %s' % (msg.body, msg.to))

        recipient = msg.to

        for message in [msg.body[i:i + DISCORD_MESSAGE_SIZE_LIMIT] for i in
                        range(0, len(msg.body), DISCORD_MESSAGE_SIZE_LIMIT)]:

            asyncio.run_coroutine_threadsafe(recipient.trigger_typing(), loop=self.client.loop)
            asyncio.run_coroutine_threadsafe(recipient.send(content=message), loop=self.client.loop)

            super().send_message(msg)

    def send_card(self, card):
        if isinstance(card.to, RoomOccupant):
            card.to = card.to.room

        recipient = discord.utils.get(self.client.get_all_channels(), name=card.to.name)

        if card.color:
            color = COLORS[card.color] if card.color in COLORS else int(card.color.replace('#', '0x'), 16)
        else:
            color = None

        # Create Embed object
        em = discord.Embed(title=card.title, description=card.summary, color=color)

        if card.image:
            em.set_image(url=card.image)

        if card.thumbnail:
            em.set_thumbnail(url=card.thumbnail)

        if card.fields:
            for key, value in card.fields:
                em.add_field(name=key, value=value, inline=True)

        asyncio.run_coroutine_threadsafe(card.to.trigger_typing(), loop=self.client.loop)
        asyncio.run_coroutine_threadsafe(recipient.send(embed=em), loop=self.client.loop)

    def build_reply(self, mess, text=None, private=False, threaded=False):
        log.debug('Threading is %s' % threaded)
        response = self.build_message(text)

        if mess.is_direct:
            response.frm = self.bot_identifier
            response.to = mess.frm
        else:
            response.frm = DiscordRoomOccupant(self.bot_identifier, response.to)
            response.to = DiscordPerson(mess.frm) if private else mess.to
        return response

    def serve_once(self):
        self.connect_callback()
        # Hehe client.run cannot be used as we need more control.
        try:
            self.client.loop.run_until_complete(self.client.start(self.token))
        except KeyboardInterrupt:
            self.client.loop.run_until_complete(self.client.logout())
            pending = asyncio.Task.all_tasks()
            gathered = asyncio.gather(*pending)
            try:
                gathered.cancel()
                self.client.loop.run_until_complete(gathered)

                # we want to retrieve any exceptions to make sure that
                # they don't nag us about it being un-retrieved.
                gathered.exception()
            except:
                pass
            self.disconnect_callback()
            return True

    def change_presence(self, status: str = ONLINE, message: str = ''):
        log.debug('Presence changed to %s and activity "%s".' % (status, message))
        activity = discord.Activity(name=message)
        self.client.change_presence(status=status, activity=activity)

    def prefix_groupchat_reply(self, message, identifier: Person):
        message.body = '@{0} {1}'.format(identifier.nick, message.body)

    def rooms(self):
        return [DiscordRoom(channel.name) for channel in self.client.get_all_channels()]

    @property
    def mode(self):
        return 'discord'
