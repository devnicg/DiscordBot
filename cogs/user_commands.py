"""
User-accessible slash commands (available in any channel, usable by anyone):
  /reset-request      — delete current onboarding channel and start fresh
  /retry-application  — re-ping country officials for a pending embassy approval
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)


class UserCommandsCog(commands.Cog, name='UserCommandsCog'):
    def __init__(self, bot):
        self.bot = bot

    # ── /reset-request ────────────────────────────────────────────────────────

    @app_commands.command(
        name='reset-request',
        description='Delete your current onboarding channel and start the application over.'
    )
    async def reset_request(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        request = await self.bot.db.get_user_request(str(member.id), str(guild.id))
        if not request:
            await interaction.response.send_message(
                'You have no active application to reset.', ephemeral=True
            )
            return

        # Delete the onboarding channel
        channel_id = request.get('channel_id')
        if channel_id:
            channel = guild.get_channel(int(channel_id))
            if channel:
                try:
                    await channel.delete(reason=f'{member.name} used /reset-request')
                except discord.Forbidden:
                    log.warning(f'Cannot delete channel {channel_id}')

        # Remove any scheduled deletion for that channel
        if channel_id:
            await self.bot.db.remove_deletion(channel_id)

        # Clear DB records
        await self.bot.db.delete_user_request(str(member.id), str(guild.id))

        await interaction.response.send_message(
            '🔄 Your application has been reset. Rejoining the server will start a new one.',
            ephemeral=True
        )

        # Re-trigger onboarding immediately
        cog = self.bot.get_cog('OnboardingCog')
        if cog:
            await cog.start_onboarding(member)

    # ── /retry-application ────────────────────────────────────────────────────

    @app_commands.command(
        name='retry-application',
        description='Re-ping your country\'s officials for a pending embassy approval.'
    )
    async def retry_application(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        request = await self.bot.db.get_user_request(str(member.id), str(guild.id))
        if not request or request.get('status') not in ('awaiting_approval', 'completed'):
            await interaction.response.send_message(
                'You have no pending embassy application to retry.', ephemeral=True
            )
            return

        embassy_req = await self.bot.db.get_embassy_request(str(member.id), str(guild.id))
        if not embassy_req or embassy_req.get('approval_status') != 'pending':
            await interaction.response.send_message(
                'No pending embassy approval found for your account.', ephemeral=True
            )
            return

        embassy_channel_id = embassy_req.get('embassy_channel_id')
        if not embassy_channel_id:
            await interaction.response.send_message(
                'Embassy channel not found. Please contact an admin.', ephemeral=True
            )
            return

        embassy_channel = guild.get_channel(int(embassy_channel_id))
        if not embassy_channel:
            await interaction.response.send_message(
                'Embassy channel no longer exists. Please contact an admin.', ephemeral=True
            )
            return

        # Find country officials
        cog = self.bot.get_cog('OnboardingCog')
        officials = []
        if cog:
            officials = await cog._find_country_officials(guild, embassy_req.get('country_id'))

        if not officials:
            await interaction.response.send_message(
                '⚠️ No officials from your country are currently registered in this Discord.\n'
                'Try again later when an official has joined.',
                ephemeral=True
            )
            return

        official_mentions = ' '.join(o.mention for o in officials)
        await embassy_channel.send(
            f'📨 **Retry:** {member.mention} is still awaiting embassy approval.\n'
            f'Officials: {official_mentions}'
        )
        await interaction.response.send_message(
            f'✅ Re-pinged your country\'s officials in {embassy_channel.mention}.', ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(UserCommandsCog(bot))
