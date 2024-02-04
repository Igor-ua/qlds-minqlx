import asyncio

from minqlx import Plugin

from discord.ext.commands import Cog
from discord import TextChannel
from discord import Embed


class AdminEventsCog(Cog):
    """
    Uses:
    * qlx_discordAdminEventsChannelId (default: "") channel id to forward admin events towards
    * qlx_discordRelaxLogoUrl (default: "") URL of the icon for discord Embed
    * qlx_discordBannedLogoUrl (default: "") URL of the thumbnail for discord Embed
    """

    def __init__(self, bot):
        Plugin.set_cvar_once("qlx_discordAdminEventsChannelId", "")
        Plugin.set_cvar_once("qlx_discordRelaxLogoUrl", "")
        Plugin.set_cvar_once("qlx_discordBannedLogoUrl", "")

        self.bot = bot

        self.discord_admin_events_channel_id = Plugin.get_cvar("qlx_discordAdminEventsChannelId", int) or -1
        self.relax_logo = Plugin.get_cvar("qlx_discordRelaxLogoUrl") or ""
        self.banned_logo = Plugin.get_cvar("qlx_discordBannedLogoUrl") or ""

    @Cog.listener()
    async def on_ban_event(self, ban_info):
        embed = self.get_ban_embed(ban_info)
        asyncio.run_coroutine_threadsafe(self.forward_embed_to_admin_channel(embed), loop=self.bot.loop)

    def get_ban_embed(self, ban_info):
        embed = Embed(color=0xe44407)
        embed.set_author(name=ban_info["server"], icon_url=self.relax_logo)

        # Choose one of the thumbnail or image property
        # set_thumbnail adds a smaller image in the corner
        # set_image adds a big image under the description
        embed.set_thumbnail(url=self.banned_logo)
        # embed.set_image(url=self.banned_logo)

        # ban_info["reason"] comes in a format "reason text"
        reason = ban_info["reason"]
        if reason and reason.startswith("reason"):
            reason = reason.split("reason ")[1]

        embed.description = f'```' \
                            f'Banned:     {ban_info["ban_target"]}' \
                            f'\nReason:     {reason}' \
                            f'\nTerm:       {ban_info["term"]}' \
                            f'\nIssued:     {ban_info["issued"]}' \
                            f'\nExpires:    {ban_info["expires"]}' \
                            f'\nAdmin ID:   {ban_info["player"].steam_id}' \
                            f'\nAdmin Name: {ban_info["player"].clean_name}' \
                            f'```'
        return embed

    async def forward_msg_to_admin_channel(self, msg):
        admin_channel = self.bot.get_channel(self.discord_admin_events_channel_id)
        if admin_channel is None or not isinstance(admin_channel, TextChannel):
            return

        await admin_channel.send(content=msg)

    async def forward_embed_to_admin_channel(self, embed):
        admin_channel = self.bot.get_channel(self.discord_admin_events_channel_id)
        if admin_channel is None or not isinstance(admin_channel, TextChannel):
            return

        await admin_channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AdminEventsCog(bot))
