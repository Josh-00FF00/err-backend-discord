import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import List, Optional, Union

from discord.utils import find
from errbot.backends.base import Person, Message, Room, RoomOccupant, Presence, \
    ONLINE, OFFLINE, AWAY, DND, RoomError

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
DISCORD_MESSAGE_SIZE_LIMIT = 4096

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
    def get_discord_object(self) -> discord.abc.Messageable:
        raise NotImplementedError


class DiscordPerson(Person, DiscordSender, discord.abc.Snowflake):

    @classmethod
    def username_and_discriminator_to_userid(cls, username: str, discriminator: str) -> str:
        return find(lambda m: m.name == username and m.discriminator == discriminator, DiscordBackend.client
                    .get_all_members())

    def __init__(self, user_id: str):
        self._user_id = user_id

    def get_discord_object(self) -> discord.abc.Messageable:
        return self.discord_user()

    @property
    def created_at(self):
        return discord.utils.snowflake_time(self.id)

    @property
    def person(self) -> str:
        return str(self)

    @property
    def id(self) -> str:
        return self._user_id

    def discord_user(self) -> discord.User:
        return DiscordBackend.client.get_user(self._user_id)

    @property
    def username(self) -> str:
        """Convert a Discord user ID to their user name"""
        user = self.discord_user()

        if user is None:
            log.error('Cannot find user with ID %s', self._user_id)
            return f'<{self._user_id}>'

        return user.name

    nick = username

    @property
    def client(self) -> None:
        return None

    @property
    def fullname(self) -> Optional[str]:
        usr = self.discord_user()

        if usr is None:
            return None

        return f"{usr.name}#{usr.discriminator}"

    @property
    def aclattr(self) -> str:
        return self.fullname

    async def send(self, content: str = None, embed: discord.Embed = None):
        await self.discord_user().send(content=content, embed=embed)

    def __eq__(self, other):
        return isinstance(other, DiscordPerson) and other.aclattr == self.aclattr

    def __str__(self):
        return self.fullname


class DiscordRoom(Room, DiscordSender, discord.abc.Snowflake):
    """
    DiscordRoom objects can be in two states:

    1. They exist and we have a channel_id of that room
    2. They don't currently exist and we have a channel name and guild
    """

    @classmethod
    def from_id(cls, channel_id):
        channel = DiscordBackend.client.get_channel(channel_id)
        if channel is None:
            raise ValueError("Channel id:{} doesn't exist!".format(channel_id))

        return cls(channel.name, channel.guild.id)

    def __init__(self, channel_name: str, guild_id: str):
        """
        Allows to specify an existing room (via name + guild or via id) or allows the creation of a future room by
        specifying a name and guild to create the channel in.

        :param channel_name:
        :param guild_id:
        """

        if DiscordBackend.client.get_guild(guild_id) is None:
            raise ValueError("Can't find guild id {} to init DiscordRoom".format(guild_id))

        self._guild_id = guild_id
        self._channel_name = channel_name
        self._channel_id = self.channel_name_to_id()  # Can be None if channel doesn't exist

    def get_discord_object(self):
        return self.discord_channel()

    def channel_name_to_id(self):
        """
        Channel names are non-unique across Discord. Hence we require a guild name to uniquely identify a room id

        :return: ID of the room
        """
        matching = [channel for channel in DiscordBackend.client.get_all_channels() if self._channel_name == channel.name
                    and channel.guild.id == self._guild_id
                    and isinstance(channel, discord.TextChannel)]

        if len(matching) == 0:
            return None

        if len(matching) > 1:
            log.warning("Multiple matching channels for channel name {} in guild id {}"
                        .format(self._channel_name, self._guild_id))

        return matching[0].id

    @property
    def created_at(self):
        return discord.utils.snowflake_time(self.id)

    def invite(self, *args) -> None:
        if not self.exists:
            raise RuntimeError("Can't invite to a non-existent channel")

        for identifier in args:
            if not isinstance(identifier, DiscordPerson):
                raise RuntimeError("Can't invite non Discord Users")

            asyncio.run_coroutine_threadsafe(
                self.discord_channel().set_permissions(identifier.discord_user(), read_messages=True),
                loop=DiscordBackend.client.loop)

    @property
    def joined(self) -> bool:
        log.error('Not implemented')
        return True

    def leave(self, reason: str = None) -> None:
        """
        Can't just leave a room
        :param reason:
        :return:
        """
        log.error('Not implemented')

    async def create_room(self):
        guild = DiscordBackend.client.get_guild(self._guild_id)

        channel = await guild.create_text_channel(self._channel_name)

        log.info("Created channel {} in guild {}".format(self._channel_name, guild.name))

        self._channel_id = channel.id

    def create(self) -> None:
        if self.exists:
            log.warning("Trying to create an already existing channel {}".format(self._channel_name))
            raise RoomError("Room exists")

        asyncio.run_coroutine_threadsafe(self.create_room(), loop=DiscordBackend.client.loop).result(timeout=5)

    def destroy(self) -> None:
        if not self.exists:
            log.warning("Trying to destory a non-existing channel {}".format(self._channel_name))
            raise RoomError("Room doesn't exist")

        asyncio.run_coroutine_threadsafe(self.discord_channel().delete(reason="Bot deletion command"),
                                         loop=DiscordBackend.client.loop).result(timeout=5)

    def join(self, username: str = None, password: str = None) -> None:
        """
        All public channels are already joined. Only private channels can be joined and we need an invite for that
        :param username:
        :param password:
        :return:
        """
        raise RuntimeError("Can't join channels")

    @property
    def topic(self) -> str:
        if not self.exists:
            return ""

        topic = self.discord_channel().topic
        topic = "" if topic is None else topic

        return topic

    @property
    def occupants(self) -> List[RoomOccupant]:
        if not self.exists:
            return []

        occupants = []
        for member in self.discord_channel().members:
            occupants.append(DiscordRoomOccupant(member.id, self._channel_id))

        return occupants

    @property
    def exists(self) -> bool:
        return self._channel_id is not None and DiscordBackend.client.get_channel(self._channel_id) is not None

    @property
    def guild(self):
        """
        Gets the guild_id this channel belongs to. None if it doesn't exist
        :return: Guild id or None
        """

        return self._guild_id

    @property
    def name(self) -> str:
        """
        Gets the channels' name

        :return: channels' name
        """
        if self._channel_id is None:
            return self._channel_name
        else:
            self._channel_name = DiscordBackend.client.get_channel(self._channel_id).name
            return self._channel_name

    @property
    def id(self):
        """
        Can return none if not created
        :return: Channel ID or None
        """
        return self._channel_id

    def discord_channel(self) -> Optional[Union[discord.abc.GuildChannel, discord.abc.PrivateChannel]]:
        return DiscordBackend.client.get_channel(self._channel_id)

    async def send(self, content: str = None, embed: discord.Embed = None):
        if not self.exists:
            raise RuntimeError("Can't send a message on a non-existent channel")
        if not isinstance(self.discord_channel(), discord.abc.Messageable):
            raise RuntimeError("Channel {}[id:{}] doesn't support sending text messages"
                               .format(self.name, self._channel_id))

        await self.discord_channel().send(content=content, embed=embed)

    def __str__(self):
        return "<#{}>".format(self.id)

    def __eq__(self, other: 'DiscordRoom'):
        if not isinstance(other, DiscordRoom):
            return False

        return other.id is not None and self.id is not None \
               and other.id == self.id


class DiscordCategory(DiscordRoom, Room):

    def channel_name_to_id(self):
        """
        Channel names are non-unique across Discord. Hence we require a guild name to uniquely identify a room id

        :return: ID of the room
        """
        matching = [channel for channel in DiscordBackend.client.get_all_channels() if self._channel_name == channel.name
                    and channel.guild.id == self._guild_id
                    and isinstance(channel, discord.CategoryChannel)]

        if len(matching) == 0:
            return None

        if len(matching) > 1:
            log.warning("Multiple matching channels for channel name {} in guild id {}"
                        .format(self._channel_name, self._guild_id))

        return matching[0].id

    def create_subchannel(self, name: str) -> DiscordRoom:
        category = self.get_discord_object()

        if not isinstance(category, discord.CategoryChannel):
            raise RuntimeError("Category is not a discord category object")

        text_channel = asyncio.run_coroutine_threadsafe(category.create_text_channel(name),
                                                        loop=DiscordBackend.client.loop).result(timeout=5)

        return DiscordRoom.from_id(text_channel.id)

    async def create_room(self):
        guild = DiscordBackend.client.get_guild(self._guild_id)

        channel = await guild.create_category(self._channel_name)

        log.info("Created category {} in guild {}".format(self._channel_name, guild.name))

        self._channel_id = channel.id

    def join(self, username: str = None, password: str = None) -> None:
        raise RuntimeError("Can't join categories")

    def leave(self, reason: str = None) -> None:
        raise RuntimeError("Can't leave categories")

    @property
    def joined(self) -> bool:
        raise RuntimeError("Can't join categories")

    @property
    def topic(self) -> str:
        raise RuntimeError("Can't set category topic")

    @property
    def occupants(self) -> List[RoomOccupant]:
        raise NotImplementedError("Not implemented yet")

    def invite(self, *args) -> None:
        raise RuntimeError("Can't invite to categories")


class DiscordRoomOccupant(DiscordPerson, RoomOccupant, DiscordSender, discord.abc.Snowflake):

    def __init__(self, user_id: str, channel_id: str):
        super().__init__(user_id)

        self._channel = DiscordRoom.from_id(channel_id)

    @property
    def room(self) -> DiscordRoom:
        return self._channel

    async def send(self, content: str = None, embed: discord.Embed = None):
        await self.room.send(content=content, embed=embed)

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

    client = None

    def __init__(self, config):
        super().__init__(config)
        identity = config.BOT_IDENTITY

        self.token = identity.get('token', None)
        self.rooms_to_join = config.CHATROOM_PRESENCE

        if not self.token:
            log.fatal('You need to set a token entry in the BOT_IDENTITY setting of your configuration.')
            sys.exit(1)
        self.bot_identifier = None

        DiscordBackend.client = discord.Client()
        self.on_ready = DiscordBackend.client.event(self.on_ready)
        self.on_message = DiscordBackend.client.event(self.on_message)
        self.on_member_update = DiscordBackend.client.event(self.on_member_update)

    async def on_ready(self):
        log.debug('Logged in as {}, {}'.format(DiscordBackend.client.user.name, DiscordBackend.client.user.id))
        if self.bot_identifier is None:
            self.bot_identifier = DiscordPerson(DiscordBackend.client.user.id)

        for channel in DiscordBackend.client.get_all_channels():
            log.debug('Found channel: %s', channel)

    async def on_message(self, msg: discord.Message):
        err_msg = Message(msg.content)

        if isinstance(msg.channel, discord.abc.PrivateChannel):
            err_msg.frm = DiscordPerson(msg.author.id)
            err_msg.to = self.bot_identifier
        else:
            err_msg.to = DiscordRoom.from_id(msg.channel.id)
            err_msg.frm = DiscordRoomOccupant(msg.author.id, msg.channel.id)

        if self.process_message(err_msg):
            # Message contains a command
            recipient = err_msg.frm

            if not isinstance(recipient, DiscordSender):
                raise ValueError("Message object from is not a DiscordSender")

            async with recipient.get_discord_object().typing():
                self._dispatch_to_plugins('callback_message', err_msg)

        if msg.mentions:
            self.callback_mention(err_msg,
                                  [DiscordRoomOccupant(mention.id, msg.channel.id)
                                   for mention in msg.mentions])

    def is_from_self(self, msg: Message) -> bool:
        other = msg.frm

        if not isinstance(other, DiscordPerson):
            return False

        return other.id == self.bot_identifier.id

    async def on_member_update(self, before, after):
        if before.status != after.status:
            person = DiscordPerson(after.id)

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
        """
        Major hacky function. we just implicitly assume we're just in one guild server.

        ##category -> a category
        #room -> Creates a room

        :param room:
        :return:
        """

        guild = DiscordBackend.client.guilds[0]

        room_name = room
        if room_name.startswith("##"):
            return DiscordCategory(room_name[2:], guild.id)
        elif room_name.startswith("#"):
            return DiscordRoom(room_name[1:], guild.id)

    def send_message(self, msg: Message):
        # log.debug('{} -> {}'.format(msg.frm, msg.to))

        recipient = msg.to

        if not isinstance(recipient, DiscordSender):
            raise RuntimeError("{} doesn't support sending messages. Expected {} but got {}"
                               .format(recipient, DiscordSender, type(recipient)))

        for message in [msg.body[i:i + DISCORD_MESSAGE_SIZE_LIMIT] for i in
                        range(0, len(msg.body), DISCORD_MESSAGE_SIZE_LIMIT)]:
            asyncio.run_coroutine_threadsafe(recipient.send(content=message), loop=DiscordBackend.client.loop)

            super().send_message(msg)

    def send_card(self, card):
        recipient = card.to

        if not isinstance(recipient, DiscordSender):
            raise RuntimeError("{} doesn't support sending messages. Expected {} but got {}"
                               .format(recipient, DiscordSender, type(recipient)))

        if card.color:
            color = COLOURS[card.color] if card.color in COLOURS else int(card.color.replace('#', '0x'), 16)
        else:
            color = None

        # Create Embed object
        em = discord.Embed(title=card.title, description=card.body, color=color)

        if card.image:
            em.set_image(url=card.image)

        if card.thumbnail:
            em.set_thumbnail(url=card.thumbnail)

        if card.fields:
            for key, value in card.fields:
                em.add_field(name=key, value=value, inline=True)

        asyncio.run_coroutine_threadsafe(recipient.send(embed=em), loop=DiscordBackend.client.loop).result(5)

    def build_reply(self, mess, text=None, private=False, threaded=False):
        response = self.build_message(text)

        if mess.is_direct:
            response.frm = self.bot_identifier
            response.to = mess.frm
        else:
            if not isinstance(mess.frm, DiscordRoomOccupant):
                raise RuntimeError("Non-Direct messages must come from a room occupant")

            response.frm = DiscordRoomOccupant(self.bot_identifier.id, mess.frm.room.id)
            response.to = DiscordPerson(mess.frm.id) if private else mess.to
        return response

    def serve_once(self):
        self.connect_callback()
        # client.run cannot be used as we need more control.
        try:
            DiscordBackend.client.loop.run_until_complete(DiscordBackend.client.start(self.token))
        except KeyboardInterrupt:
            DiscordBackend.client.loop.run_until_complete(DiscordBackend.client.logout())
            pending = asyncio.Task.all_tasks()
            gathered = asyncio.gather(*pending)
            # noinspection PyBroadException
            try:
                gathered.cancel()
                DiscordBackend.client.loop.run_until_complete(gathered)

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
        DiscordBackend.client.change_presence(status=status, activity=activity)

    def prefix_groupchat_reply(self, message, identifier: Person):
        message.body = '@{0} {1}'.format(identifier.nick, message.body)

    def rooms(self):
        return [DiscordRoom.from_id(channel.id) for channel in DiscordBackend.client.get_all_channels()]

    @property
    def mode(self):
        return 'discord'

    def build_identifier(self, string_representation: str):
        """
        This needs a major rethink/rework since discord bots can be in different Guilds so room name clashes are
        certainly possible. For now we are only uniquely identifying users

        Valid forms of strreps:
        user#discriminator      -> Person

        :param string_representation:
        :return: Identifier
        """
        if not string_representation:
            raise ValueError('Empty strrep')

        if '#' in string_representation:
            user, discriminator = string_representation.split('#')
        else:
            raise ValueError("No Discriminator")

        user_id = DiscordPerson.username_and_discriminator_to_userid(user, discriminator)

        return DiscordPerson(user_id=user_id)
