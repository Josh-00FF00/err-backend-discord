import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import List, Optional, Union

from errbot.backends.base import Person, Message, Room, RoomOccupant, Presence, \
    ONLINE, OFFLINE, AWAY, DND, Identifier
from errbot.core import ErrBot

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

COLOURS = {
    'red': 0xFF0000,
    'green': 0x008000,
    'yellow': 0xFFA500,
    'blue': 0x0000FF,
    'white': 0xFFFFFF,
    'cyan': 0x00FFFF
}  # Discord doesn't know its colours


class DiscordSender(ABC):
    @abstractmethod
    async def send(self, content: str = None, embed: discord.Embed = None):
        raise NotImplementedError

    @abstractmethod
    async def trigger_typing(self):
        raise NotImplementedError


class DiscordPerson(Person, DiscordSender, discord.abc.Snowflake):

    def __init__(self, dc: discord.Client, user_id: str):
        self._user_id = user_id
        self._dc = dc

    @property
    def created_at(self):
        return discord.utils.snowflake_time(self.id)

    @property
    def person(self) -> str:
        return self._user_id

    @property
    def id(self) -> str:
        return self._user_id

    @property
    def discord_user(self) -> discord.User:
        return self._dc.get_user(self._user_id)

    @property
    def username(self) -> str:
        """Convert a Discord user ID to their user name"""
        user = self.discord_user

        if user is None:
            log.error('Cannot find user with ID %s', self._user_id)
            return f'<{self._user_id}>'

        return user.name

    nick = username

    @property
    def client(self) -> None:
        return None

    @property
    def fullname(self) -> str:
        return f"{self.discord_user.name}#{self.discord_user.discriminator}"

    @property
    def aclattr(self) -> str:
        return self._user_id

    async def send(self, content: str = None, embed: discord.Embed = None):
        await self.discord_user.send(content=content, embed=embed)

    async def trigger_typing(self):
        await self.discord_user.trigger_typing()

    def __eq__(self, other):
        return isinstance(other, DiscordPerson) and other.aclattr == self.aclattr

    def __str__(self):
        return self.fullname


class DiscordRoom(Room, DiscordSender, discord.abc.Snowflake):

    def __init__(self, dc: discord.Client, channel_id: str = None, channel_name: str = None):
        if channel_id is not None and channel_name is not None:
            raise ValueError("channel_id and channel_name are mutually exclusive")

        if channel_name is not None:
            # Channel doesn't exist
            self._channel_name = channel_name
            self._channel_id = None
        else:
            # Channel exists
            self._channel_id = channel_id
            self._channel_name = dc.get_channel(channel_id).name

        self._dc = dc

    @property
    def created_at(self):
        return discord.utils.snowflake_time(self.id)

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
        return self._channel_id is not None

    @property
    def guild(self):
        """
        Gets the guild_id this channel belongs to. None if it doesn't exist
        :return: Guild id or None
        """
        if not self.exists:
            return None

        channel = self._dc.get_channel(self._channel_id)
        return channel.guild.id

    @property
    def name(self) -> str:
        """
        Gets the channels' name

        :return: channels' name
        """
        if self._channel_id is None:
            return self._channel_name
        else:
            return self._dc.get_channel(self._channel_id).name

    @property
    def id(self):
        """
        Can return none if not created
        :return: Channel ID or None
        """
        return self._channel_id

    @property
    def discord_channel(self) -> Optional[Union[discord.abc.GuildChannel, discord.abc.PrivateChannel]]:
        return self._dc.get_channel(self._channel_id)

    async def send(self, content: str = None, embed: discord.Embed = None):
        if not self.exists:
            raise RuntimeError("Can't send a message on a non-existent channel")
        if not isinstance(self.discord_channel, discord.abc.Messageable):
            raise RuntimeError("Channel {}[id:{}] doesn't support sending text messages"
                               .format(self.name, self._channel_id))

        await self.discord_channel.send(content=content, embed=embed)

    async def trigger_typing(self):
        if not self.exists:
            raise RuntimeError("Can't start typing on a non-existent channel")
        if not isinstance(self.discord_channel, discord.abc.Messageable):
            raise RuntimeError("Channel {}[id:{}] doesn't support typing"
                               .format(self.name, self._channel_id))

        await self.discord_channel.trigger_typing()

    def __str__(self):
        return '#' + self.name

    def __eq__(self, other: 'DiscordRoom'):
        if not isinstance(other, DiscordRoom):
            return False

        return other.id is not None and self.id is not None \
            and other.id == self.id


class DiscordRoomOccupant(DiscordPerson, RoomOccupant, DiscordSender, discord.abc.Snowflake):

    def __init__(self, dc: discord.Client, user_id: str, channel_id: str):
        super().__init__(dc, user_id)

        self._channel = DiscordRoom(dc, channel_id)
        self._dc = dc

    @property
    def room(self) -> DiscordRoom:
        return self._channel

    async def send(self, content: str = None, embed: discord.Embed = None):
        await self.room.send(content=content, embed=embed)

    async def trigger_typing(self):
        await self.room.trigger_typing()

    def __eq__(self, other):
        return isinstance(other, DiscordRoomOccupant) \
               and other.id == self.id \
               and other.room.id == self.room.id

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
            self.bot_identifier = DiscordPerson(self.client, self.client.user.id)

        for channel in self.client.get_all_channels():
            log.debug('Found channel: %s', channel)

    async def on_message(self, msg: discord.Message):
        err_msg = Message(msg.content)

        if isinstance(msg.channel, discord.abc.PrivateChannel):
            err_msg.frm = DiscordPerson(self.client, msg.author.id)
            err_msg.to = self.bot_identifier
        else:
            err_msg.to = DiscordRoom(self.client, msg.channel.id)
            err_msg.frm = DiscordRoomOccupant(self.client, msg.author.id, msg.channel.id)

        log.debug('Received message %s' % msg)

        self.callback_message(err_msg)

        if msg.mentions:
            self.callback_mention(err_msg,
                                  [DiscordRoomOccupant(self.client, mention.id, msg.channel.id)
                                   for mention in msg.mentions])

    def is_from_self(self, msg: Message) -> bool:
        return msg.frm == self.bot_identifier

    async def on_member_update(self, before, after):
        if before.status != after.status:
            person = DiscordPerson(self.client, after)

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

        if not isinstance(recipient, DiscordSender):
            raise RuntimeError("{} doesn't support sending messages. Expected {} but got {}"
                               .format(recipient, DiscordSender, type(recipient)))

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
            color = COLOURS[card.color] if card.color in COLOURS else int(card.color.replace('#', '0x'), 16)
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
            if not isinstance(mess.frm, DiscordRoomOccupant):
                raise RuntimeError("Non-Direct messages must come from a room occupant")

            response.frm = DiscordRoomOccupant(self.client, self.bot_identifier.id, mess.frm.room.id)
            response.to = DiscordPerson(self.client, mess.frm.id) if private else mess.to
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
