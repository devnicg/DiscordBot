"""
Admin & Senate commands:
  /setup           — interactive wizard (admin only)
  /test-onboarding — simulate member join for a user
  /test-visitor    — complete visitor flow for a user
  /test-citizen    — complete citizen flow for a user (skips country check)
  /test-embassy    — complete embassy flow for a user
"""

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from country_flags import get_flag
from warera_api import get_user_lite, get_government_role, get_country_by_id, extract_user_id, CONGO_LOCAL_ROLES, CONGO_COUNTRY_ID

log = logging.getLogger(__name__)


# ── Setup wizard views ────────────────────────────────────────────────────────

class SetupCategorySelect(discord.ui.View):
    def __init__(self, bot, user_id: int, step: str, categories: list):
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = user_id
        self.step = step  # 'onboarding' or 'embassy'

        options = [
            discord.SelectOption(label=cat.name[:100], value=str(cat.id))
            for cat in categories[:25]
        ]
        options.append(discord.SelectOption(label='➕ Create new category', value='__create__'))

        select = discord.ui.Select(
            placeholder=f'Select {step} category…',
            options=options,
            custom_id=f'setup_category_{step}'
        )
        select.callback = self._callback
        self.add_item(select)

    async def _callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('Not your setup.', ephemeral=True)
            return
        value = interaction.data['values'][0]
        guild = interaction.guild

        if value == '__create__':
            if self.step == 'onboarding':
                cat = await guild.create_category('📬 Onboarding')
            else:
                cat = await guild.create_category('🏛️ Embassies')
            value = str(cat.id)

        key = 'onboarding_category_id' if self.step == 'onboarding' else 'embassy_category_id'
        await self.bot.db.set_guild_config(str(guild.id), **{key: value})

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f'✅ {self.step.capitalize()} category set.',
            view=self
        )


class SetupRoleSelect(discord.ui.View):
    def __init__(self, bot, user_id: int, step: str, roles: list,
                 db_key: str = None, can_create: bool = None):
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = user_id
        self.step = step  # display label, e.g. 'senate', 'visitor', 'President'
        self.db_key = db_key if db_key is not None else f'{step}_role_id'

        # Default: only visitor/citizen offer auto-create; callers can override
        _can_create = can_create if can_create is not None else step in ('visitor', 'citizen')

        options = [
            discord.SelectOption(label=r.name[:100], value=str(r.id))
            for r in roles[:24]
        ]
        if _can_create:
            # Use the step name as-is for properly-cased labels (e.g. 'President'),
            # capitalize() for lowercase legacy steps ('visitor' → 'Visitor').
            label = step if step[0].isupper() else step.capitalize()
            options.append(discord.SelectOption(label=f'➕ Create "{label}" role', value='__create__'))

        select = discord.ui.Select(
            placeholder=f'Select {step} role…',
            options=options,
            custom_id=f'setup_role_{step.lower().replace(" ", "_")}'
        )
        select.callback = self._callback
        self.add_item(select)

    async def _callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('Not your setup.', ephemeral=True)
            return
        value = interaction.data['values'][0]
        guild = interaction.guild

        if value == '__create__':
            role_name = self.step if self.step[0].isupper() else self.step.capitalize()
            role = await guild.create_role(name=role_name, mentionable=True)
            value = str(role.id)

        await self.bot.db.set_guild_config(str(guild.id), **{self.db_key: value})

        for item in self.children:
            item.disabled = True
        label = self.step if self.step[0].isupper() else self.step.capitalize()
        await interaction.response.edit_message(
            content=f'✅ {label} role set.',
            view=self
        )


# ── Admin Cog ─────────────────────────────────────────────────────────────────

class AdminCog(commands.Cog, name='AdminCog'):
    def __init__(self, bot):
        self.bot = bot

    async def _is_senate(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        config = await self.bot.db.get_guild_config(str(interaction.guild.id))
        if not config or not config.get('senate_role_id'):
            return False
        senate_role = interaction.guild.get_role(int(config['senate_role_id']))
        return senate_role is not None and senate_role in interaction.user.roles

    # ── /setup ────────────────────────────────────────────────────────────────

    @app_commands.command(name='setup', description='Configure the Congo bot (admin only).')
    @app_commands.default_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction):
        guild = interaction.guild
        categories = [c for c in guild.categories]
        roles = [r for r in guild.roles if not r.is_default() and not r.managed]

        total_steps = 5 + len(CONGO_LOCAL_ROLES)
        await interaction.response.send_message(
            f'**Congo Bot Setup — Step 1/{total_steps}**\nSelect the category where **onboarding channels** will be created:',
            view=SetupCategorySelect(self.bot, interaction.user.id, 'onboarding', categories),
            ephemeral=True
        )
        # Show a summary of current config
        config = await self.bot.db.get_guild_config(str(guild.id))
        if config:
            lines = []
            for key, label in [
                ('onboarding_category_id', 'Onboarding category'),
                ('embassy_category_id', 'Embassy category'),
                ('senate_role_id', 'Senate role'),
                ('visitor_role_id', 'Visitor role'),
                ('citizen_role_id', 'Citizen role'),
            ] + [(db_key, f'Congo {name}') for _, db_key, name in CONGO_LOCAL_ROLES]:
                val = config.get(key)
                if val:
                    obj = guild.get_channel(int(val)) or guild.get_role(int(val))
                    lines.append(f'✅ {label}: **{obj.name if obj else val}**')
                else:
                    lines.append(f'❌ {label}: *not set*')
            await interaction.followup.send('\n'.join(lines), ephemeral=True)

        await interaction.followup.send(
            f'**Step 2/{total_steps}** — Select the **Embassy category** (or create one):',
            view=SetupCategorySelect(self.bot, interaction.user.id, 'embassy', categories),
            ephemeral=True
        )
        await interaction.followup.send(
            f'**Step 3/{total_steps}** — Select the **Senate role** (existing only):',
            view=SetupRoleSelect(self.bot, interaction.user.id, 'senate', roles),
            ephemeral=True
        )
        await interaction.followup.send(
            f'**Step 4/{total_steps}** — Select or create the **Visitor role**:',
            view=SetupRoleSelect(self.bot, interaction.user.id, 'visitor', roles),
            ephemeral=True
        )
        await interaction.followup.send(
            f'**Step 5/{total_steps}** — Select or create the **Citizen role**:',
            view=SetupRoleSelect(self.bot, interaction.user.id, 'citizen', roles),
            ephemeral=True
        )
        # Steps 6–10: Congolese government roles (local Discord roles for citizens)
        for i, (_, db_key, display_name) in enumerate(CONGO_LOCAL_ROLES, start=6):
            await interaction.followup.send(
                f'**Step {i}/{total_steps}** — Select or create the **{display_name}** role '
                f'(local Congo government role):',
                view=SetupRoleSelect(
                    self.bot, interaction.user.id, display_name, roles,
                    db_key=db_key, can_create=True
                ),
                ephemeral=True
            )

    # ── /config ───────────────────────────────────────────────────────────────

    @app_commands.command(name='config', description='Show current bot config and env-var seed values (admin only).')
    @app_commands.default_permissions(administrator=True)
    async def config_show(self, interaction: discord.Interaction):
        guild = interaction.guild
        config = await self.bot.db.get_guild_config(str(guild.id)) or {}

        fields = [
            ('onboarding_category_id',       'SETUP_ONBOARDING_CATEGORY_ID'),
            ('embassy_category_id',          'SETUP_EMBASSY_CATEGORY_ID'),
            ('senate_role_id',               'SETUP_SENATE_ROLE_ID'),
            ('visitor_role_id',              'SETUP_VISITOR_ROLE_ID'),
            ('citizen_role_id',              'SETUP_CITIZEN_ROLE_ID'),
            ('local_role_president_id',      'SETUP_LOCAL_ROLE_PRESIDENT_ID'),
            ('local_role_vice_president_id', 'SETUP_LOCAL_ROLE_VICE_PRESIDENT_ID'),
            ('local_role_mfa_id',            'SETUP_LOCAL_ROLE_MFA_ID'),
            ('local_role_economy_id',        'SETUP_LOCAL_ROLE_ECONOMY_ID'),
            ('local_role_defense_id',        'SETUP_LOCAL_ROLE_DEFENSE_ID'),
            ('local_role_congress_id',       'SETUP_LOCAL_ROLE_CONGRESS_ID'),
        ]

        lines = ['**Current guild config** (copy IDs into `.env` to survive database resets)\n```']
        for db_key, env_key in fields:
            val = config.get(db_key) or 'not set'
            lines.append(f'{env_key}={val}')
        lines.append('```')

        await interaction.response.send_message('\n'.join(lines), ephemeral=True)

    # ── /admin-restore ────────────────────────────────────────────────────────

    @app_commands.command(
        name='admin-restore',
        description='[Admin] Manually restore a verified user into the database without re-running onboarding.'
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        member='The Discord member to restore',
        role_type='The role to assign',
        warera_id='Their WarEra user ID'
    )
    @app_commands.choices(role_type=[
        app_commands.Choice(name='Visitor', value='visitor'),
        app_commands.Choice(name='Citizen', value='citizen'),
        app_commands.Choice(name='Embassy', value='embassy'),
    ])
    async def admin_restore(
        self, interaction: discord.Interaction,
        member: discord.Member,
        role_type: app_commands.Choice[str],
        warera_id: str
    ):
        if not await self._is_senate(interaction):
            await interaction.response.send_message('No permission.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        config = await self.bot.db.get_guild_config(str(guild.id))
        if not config:
            await interaction.followup.send('Bot is not configured — run `/setup` first.', ephemeral=True)
            return

        resolved_id = extract_user_id(warera_id) or warera_id
        warera_data = await get_user_lite(resolved_id)
        if not warera_data:
            await interaction.followup.send(
                f'Could not find a WarEra user with ID `{resolved_id}`.',
                ephemeral=True
            )
            return
        warera_id = resolved_id

        warera_username = warera_data.get('username', warera_id)
        rt = role_type.value

        if rt == 'visitor':
            role = guild.get_role(int(config['visitor_role_id'])) if config.get('visitor_role_id') else None
            if not role:
                await interaction.followup.send('Visitor role is not configured.', ephemeral=True)
                return
            await member.add_roles(role)
            await self.bot.db.upsert_tracked_user(
                str(member.id), str(guild.id), warera_id, 'visitor',
                warera_data.get('country'), str(role.id)
            )
            await interaction.followup.send(
                f'✅ {member.mention} restored as **Visitor** (WarEra: `{warera_username}`).',
                ephemeral=True
            )

        elif rt == 'citizen':
            role = guild.get_role(int(config['citizen_role_id'])) if config.get('citizen_role_id') else None
            if not role:
                await interaction.followup.send('Citizen role is not configured.', ephemeral=True)
                return
            await member.add_roles(role)
            await self.bot.db.upsert_tracked_user(
                str(member.id), str(guild.id), warera_id, 'citizen',
                warera_data.get('country'), str(role.id)
            )
            await interaction.followup.send(
                f'✅ {member.mention} restored as **Citizen** (WarEra: `{warera_username}`).',
                ephemeral=True
            )

        elif rt == 'embassy':
            infos = warera_data.get('infos', {})
            role_field, access_level, country_id = get_government_role(infos)
            if not role_field:
                await interaction.followup.send(
                    f'`{warera_username}` has no government role in WarEra. Cannot restore as Embassy.',
                    ephemeral=True
                )
                return

            country_data = await get_country_by_id(country_id)
            country_name = country_data.get('name', 'Unknown') if country_data else 'Unknown'
            country_flag = get_flag(country_name)

            onboarding = self.bot.get_cog('OnboardingCog')
            if not onboarding:
                await interaction.followup.send('OnboardingCog not loaded.', ephemeral=True)
                return

            category = await onboarding._ensure_embassy_category(guild, config)
            emb_channel, base_role, write_role = await onboarding._ensure_embassy_channel_role(
                guild, category, country_name, country_flag, config
            )

            roles_to_add = [base_role]
            if access_level == 'write':
                roles_to_add.append(write_role)
            await member.add_roles(*roles_to_add)

            await self.bot.db.create_embassy_request(
                str(member.id), str(guild.id), country_id, country_name, country_flag,
                role_field, access_level
            )
            await self.bot.db.update_embassy_request(
                str(member.id), str(guild.id),
                embassy_channel_id=str(emb_channel.id),
                embassy_role_id=str(base_role.id),
                embassy_write_role_id=str(write_role.id),
                approval_status='approved'
            )
            await self.bot.db.upsert_tracked_user(
                str(member.id), str(guild.id), warera_id, 'embassy',
                country_id, str(base_role.id)
            )

            access_str = 'write access' if access_level == 'write' else 'read-only'
            await interaction.followup.send(
                f'✅ {member.mention} restored as **Embassy** — {country_name} {country_flag} '
                f'({access_str}, WarEra: `{warera_username}`).',
                ephemeral=True
            )

    # ── /test-onboarding ──────────────────────────────────────────────────────

    @app_commands.command(name='test-onboarding', description='[Senate] Simulate member join for a user.')
    @app_commands.describe(user='The Discord member to test onboarding for.')
    async def test_onboarding(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._is_senate(interaction):
            await interaction.response.send_message('Senate role required.', ephemeral=True)
            return
        # Remove any existing request so we start fresh
        await self.bot.db.delete_user_request(str(user.id), str(interaction.guild.id))
        cog = self.bot.get_cog('OnboardingCog')
        await interaction.response.send_message(
            f'🧪 Starting onboarding test for {user.mention}…', ephemeral=True
        )
        await cog.start_onboarding(user)

    # ── /test-visitor ─────────────────────────────────────────────────────────

    @app_commands.command(name='test-visitor', description='[Senate] Instantly complete visitor flow.')
    @app_commands.describe(user='The Discord member to test.')
    async def test_visitor(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._is_senate(interaction):
            await interaction.response.send_message('Senate role required.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        request = await self.bot.db.get_user_request(str(user.id), str(interaction.guild.id))
        if not request or not request.get('channel_id'):
            await interaction.followup.send(
                f'No active onboarding channel for {user.mention}. Run `/test-onboarding` first.',
                ephemeral=True
            )
            return
        channel = interaction.guild.get_channel(int(request['channel_id']))
        if not channel:
            await interaction.followup.send('Onboarding channel not found.', ephemeral=True)
            return

        # Build a minimal fake warera_data stub so we can call complete_visitor
        fake_data = {
            '_id': request.get('warera_id') or 'test000000000000test0000',
            'username': request.get('warera_username') or user.name,
            'country': request.get('country_id') or '',
        }
        cog = self.bot.get_cog('OnboardingCog')
        await cog.complete_visitor(channel, user, fake_data)
        await interaction.followup.send(f'✅ Visitor flow completed for {user.mention}.', ephemeral=True)

    # ── /test-citizen ─────────────────────────────────────────────────────────

    @app_commands.command(name='test-citizen', description='[Senate] Instantly complete citizen flow (skips country check).')
    @app_commands.describe(user='The Discord member to test.')
    async def test_citizen(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._is_senate(interaction):
            await interaction.response.send_message('Senate role required.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        request = await self.bot.db.get_user_request(str(user.id), str(interaction.guild.id))
        if not request or not request.get('channel_id'):
            await interaction.followup.send(
                f'No active onboarding channel for {user.mention}. Run `/test-onboarding` first.',
                ephemeral=True
            )
            return
        channel = interaction.guild.get_channel(int(request['channel_id']))
        if not channel:
            await interaction.followup.send('Onboarding channel not found.', ephemeral=True)
            return

        # Force warera_id and username if missing
        if not request.get('warera_id'):
            await self.bot.db.update_user_request(
                str(user.id), str(interaction.guild.id),
                warera_id='test000000000000test0000',
                warera_username=user.name,
                country_id='6873d0ea1758b40e712b5f4c',
                country_name='Congo',
                verification_token='TESTTOKEN',
                requested_role='citizen',
                status='awaiting_company_change'
            )
        cog = self.bot.get_cog('OnboardingCog')
        await cog.complete_citizen(channel, user)
        await interaction.followup.send(f'✅ Citizen flow completed for {user.mention}.', ephemeral=True)

    # ── /test-embassy ─────────────────────────────────────────────────────────

    @app_commands.command(name='test-embassy', description='[Senate] Instantly complete embassy flow.')
    @app_commands.describe(user='The Discord member to test.')
    async def test_embassy(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._is_senate(interaction):
            await interaction.response.send_message('Senate role required.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        request = await self.bot.db.get_user_request(str(user.id), str(interaction.guild.id))
        if not request or not request.get('channel_id'):
            await interaction.followup.send(
                f'No active onboarding channel for {user.mention}. Run `/test-onboarding` first.',
                ephemeral=True
            )
            return
        channel = interaction.guild.get_channel(int(request['channel_id']))
        if not channel:
            await interaction.followup.send('Onboarding channel not found.', ephemeral=True)
            return

        # Ensure an embassy_request record exists for the test
        emb = await self.bot.db.get_embassy_request(str(user.id), str(interaction.guild.id))
        if not emb:
            await self.bot.db.create_embassy_request(
                str(user.id), str(interaction.guild.id),
                '6873d0ea1758b40e712b5f4c', 'Congo', '🇨🇬',
                'presidentOf', 'write'
            )
        if not request.get('warera_id'):
            await self.bot.db.update_user_request(
                str(user.id), str(interaction.guild.id),
                warera_id='test000000000000test0000',
                warera_username=user.name,
                country_id='6873d0ea1758b40e712b5f4c',
                country_name='Congo',
                verification_token='TESTTOKEN',
                requested_role='embassy',
                status='awaiting_company_change'
            )
        cog = self.bot.get_cog('OnboardingCog')
        await cog.complete_embassy(channel, user)
        await interaction.followup.send(f'✅ Embassy flow completed for {user.mention}.', ephemeral=True)


    # ── /addwrite ─────────────────────────────────────────────────────────────

    @app_commands.command(
        name='addwrite',
        description='[Pres/VP/MoFA] Grant write access in your embassy to a registered member.'
    )
    @app_commands.describe(user='The Discord member to grant write access to.')
    async def addwrite(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # 1. Verify the invoker is a tracked embassy official with write-level role
        grantor_tracked = await self.bot.db.get_tracked_user(
            str(interaction.user.id), str(guild.id)
        )
        if not grantor_tracked or grantor_tracked.get('assigned_role') != 'embassy':
            await interaction.followup.send(
                'You must be a registered embassy official to use this command.', ephemeral=True
            )
            return

        warera_data = await get_user_lite(grantor_tracked['warera_id'])
        if not warera_data:
            await interaction.followup.send(
                'Could not verify your WarEra account. Try again later.', ephemeral=True
            )
            return

        infos = warera_data.get('infos', {})
        role_field, access_level, country_id = get_government_role(infos)
        if access_level != 'write':
            await interaction.followup.send(
                'Only **Presidents**, **Vice Presidents**, or **Ministers of Foreign Affairs** '
                'can grant write access.', ephemeral=True
            )
            return

        # 2. Verify the target is in the same country's embassy
        if user.id == interaction.user.id:
            await interaction.followup.send('You cannot grant write access to yourself.', ephemeral=True)
            return

        target_tracked = await self.bot.db.get_tracked_user(str(user.id), str(guild.id))
        if not target_tracked or target_tracked.get('country_id') != country_id:
            await interaction.followup.send(
                f'{user.mention} is not registered in your country\'s embassy.', ephemeral=True
            )
            return

        # 3. Find the write role for this country (predictable name)
        embassy_req = await self.bot.db.get_embassy_request(str(user.id), str(guild.id))
        if not embassy_req or not embassy_req.get('embassy_write_role_id'):
            await interaction.followup.send(
                'Could not find the embassy write role. Make sure the embassy is set up.', ephemeral=True
            )
            return

        write_role = guild.get_role(int(embassy_req['embassy_write_role_id']))
        if not write_role:
            await interaction.followup.send(
                'The embassy write role no longer exists. Please contact an admin.', ephemeral=True
            )
            return

        if write_role in user.roles:
            await interaction.followup.send(
                f'{user.mention} already has write access.', ephemeral=True
            )
            return

        # 4. Grant the write role
        try:
            await user.add_roles(write_role, reason=f'Write access granted by {interaction.user}')
        except discord.Forbidden:
            await interaction.followup.send(
                'I do not have permission to assign that role.', ephemeral=True
            )
            return

        # 5. Record the grant
        await self.bot.db.add_write_grant(
            grantor_discord_id=str(interaction.user.id),
            grantor_warera_id=grantor_tracked['warera_id'],
            grantee_discord_id=str(user.id),
            guild_id=str(guild.id),
            country_id=country_id,
            write_role_id=str(write_role.id)
        )

        # Notify in the embassy channel if it exists
        if embassy_req.get('embassy_channel_id'):
            emb_channel = guild.get_channel(int(embassy_req['embassy_channel_id']))
            if emb_channel:
                await emb_channel.send(
                    f'✅ {interaction.user.mention} has granted **write access** to {user.mention}.'
                )

        await interaction.followup.send(
            f'✅ Write access granted to {user.mention}.\n'
            '⚠️ This access will be automatically revoked if you lose your government role.',
            ephemeral=True
        )


    # ── /admin-db-status ──────────────────────────────────────────────────────

    @app_commands.command(
        name='admin-db-status',
        description='[Admin] List all members tracked in the database and verify their Discord roles match.'
    )
    @app_commands.default_permissions(administrator=True)
    async def admin_db_status(self, interaction: discord.Interaction):
        if not await self._is_senate(interaction):
            await interaction.response.send_message('No permission.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        tracked = await self.bot.db.get_all_tracked_users(str(guild.id))
        write_grants = await self.bot.db.get_all_write_grants(str(guild.id))

        if not tracked:
            await interaction.followup.send('No members in the database.', ephemeral=True)
            return

        role_emoji = {'visitor': '👤', 'citizen': '🇨🇬', 'embassy': '🏛️'}

        lines = [f'**Database status — {len(tracked)} tracked member(s)**\n']

        for t in tracked:
            member = guild.get_member(int(t['discord_id']))
            emoji = role_emoji.get(t['assigned_role'], '❓')
            name = member.mention if member else f'*(left server — ID {t["discord_id"]})*'

            # Check that their Discord role still exists and they still hold it
            discord_role = guild.get_role(int(t['discord_role_id'])) if t.get('discord_role_id') else None
            if not discord_role:
                role_status = '⚠️ role deleted'
            elif member and discord_role not in member.roles:
                role_status = '⚠️ role missing from member'
            else:
                role_status = f'✅ `{discord_role.name}`'

            country = f'`{t["country_id"]}`' if t.get('country_id') else '—'
            lines.append(
                f'{emoji} {name}\n'
                f'  Role: **{t["assigned_role"]}** | {role_status}\n'
                f'  WarEra ID: `{t["warera_id"]}` | Country: {country}'
            )

            # Show write grants where this member is the grantee
            grants_for = [g for g in write_grants if g['grantee_discord_id'] == t['discord_id']]
            for g in grants_for:
                grantor = guild.get_member(int(g['grantor_discord_id']))
                grantor_name = grantor.display_name if grantor else g['grantor_discord_id']
                write_role = guild.get_role(int(g['write_role_id'])) if g.get('write_role_id') else None
                wr_status = '✅' if (write_role and member and write_role in member.roles) else '⚠️ role missing'
                lines.append(f'  ✍️ Write grant from **{grantor_name}** {wr_status}')

            lines.append('')

        # Split into chunks to stay under Discord's 2000-char limit
        chunks, current = [], ''
        for line in lines:
            if len(current) + len(line) + 1 > 1900:
                chunks.append(current)
                current = line + '\n'
            else:
                current += line + '\n'
        if current:
            chunks.append(current)

        for chunk in chunks:
            await interaction.followup.send(chunk, ephemeral=True)

    # ── /admin-restore-write ──────────────────────────────────────────────────

    @app_commands.command(
        name='admin-restore-write',
        description='[Admin] Restore a write grant between two embassy members after a database reset.'
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        grantor='The official who originally granted write access',
        grantee='The member who received write access'
    )
    async def admin_restore_write(
        self, interaction: discord.Interaction,
        grantor: discord.Member,
        grantee: discord.Member
    ):
        if not await self._is_senate(interaction):
            await interaction.response.send_message('No permission.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        grantor_tracked = await self.bot.db.get_tracked_user(str(grantor.id), str(guild.id))
        if not grantor_tracked or grantor_tracked.get('assigned_role') != 'embassy':
            await interaction.followup.send(
                f'{grantor.mention} is not registered as an embassy member. '
                'Run `/admin-restore` for them first.',
                ephemeral=True
            )
            return

        grantee_tracked = await self.bot.db.get_tracked_user(str(grantee.id), str(guild.id))
        if not grantee_tracked:
            await interaction.followup.send(
                f'{grantee.mention} is not registered in the database. '
                'Run `/admin-restore` for them first.',
                ephemeral=True
            )
            return

        embassy_req = await self.bot.db.get_embassy_request(str(grantor.id), str(guild.id))
        if not embassy_req or not embassy_req.get('embassy_write_role_id'):
            await interaction.followup.send(
                f'Could not find the embassy write role for {grantor.mention}\'s country. '
                'Make sure their embassy is restored first.',
                ephemeral=True
            )
            return

        write_role = guild.get_role(int(embassy_req['embassy_write_role_id']))
        if not write_role:
            await interaction.followup.send(
                'The embassy write role no longer exists in Discord. '
                'Re-run `/admin-restore` for the grantor to recreate it.',
                ephemeral=True
            )
            return

        if write_role not in grantee.roles:
            try:
                await grantee.add_roles(write_role, reason=f'Write grant restored by {interaction.user}')
            except discord.Forbidden:
                await interaction.followup.send(
                    'I do not have permission to assign that role.', ephemeral=True
                )
                return

        await self.bot.db.add_write_grant(
            grantor_discord_id=str(grantor.id),
            grantor_warera_id=grantor_tracked['warera_id'],
            grantee_discord_id=str(grantee.id),
            guild_id=str(guild.id),
            country_id=embassy_req['country_id'],
            write_role_id=str(write_role.id)
        )

        await interaction.followup.send(
            f'✅ Write grant restored: {grantor.mention} → {grantee.mention} '
            f'({embassy_req.get("country_name", "unknown country")}).',
            ephemeral=True
        )


    # ── /admin-restore-localroles ─────────────────────────────────────────────

    @app_commands.command(
        name='admin-restore-localroles',
        description='[Admin] Re-link all citizens to their correct Congolese government Discord roles.'
    )
    @app_commands.default_permissions(administrator=True)
    async def admin_restore_localroles(self, interaction: discord.Interaction):
        if not await self._is_senate(interaction):
            await interaction.response.send_message('No permission.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        config = await self.bot.db.get_guild_config(str(guild.id))
        if not config:
            await interaction.followup.send('Bot is not configured — run `/setup` first.', ephemeral=True)
            return

        # Check that at least one local Congo role is configured
        configured = [db_key for _, db_key, _ in CONGO_LOCAL_ROLES if config.get(db_key)]
        if not configured:
            await interaction.followup.send(
                '⚠️ No Congolese government roles are configured yet. '
                'Run `/setup` and assign the President, Vice President, etc. roles first.',
                ephemeral=True
            )
            return

        onboarding = self.bot.get_cog('OnboardingCog')
        if not onboarding:
            await interaction.followup.send('OnboardingCog not loaded.', ephemeral=True)
            return

        tracked = await self.bot.db.get_all_tracked_users(str(guild.id))
        # Process citizens and all embassy members — sync_congo_local_roles checks
        # Congo country ID per role, so it's a no-op for non-Congolese members.
        # Filtering by stored country_id here is unreliable (can be stale).
        eligible = [
            t for t in tracked
            if t.get('assigned_role') in ('citizen', 'embassy')
        ]

        # discord_id → set of db_keys the member was confirmed to qualify for
        qualified: dict[str, set] = {}
        # discord_ids where the WarEra API failed — don't touch their roles
        api_failed: set[str] = set()

        updated, errors = 0, 0
        for t in eligible:
            member = guild.get_member(int(t['discord_id']))
            if not member:
                continue
            warera_data = await get_user_lite(t['warera_id'])
            if not warera_data:
                errors += 1
                api_failed.add(str(t['discord_id']))
                continue

            # Congolese embassy members also get the Citizen role — check live WarEra data
            if t.get('assigned_role') == 'embassy' and warera_data.get('country') == CONGO_COUNTRY_ID:
                citizen_role_id = config.get('citizen_role_id')
                if citizen_role_id:
                    citizen_role = guild.get_role(int(citizen_role_id))
                    if citizen_role and citizen_role not in member.roles:
                        try:
                            await member.add_roles(citizen_role)
                        except discord.Forbidden:
                            pass

            await onboarding.sync_congo_local_roles(guild, member, warera_data, config)
            updated += 1

            # Record which roles this member legitimately holds
            infos = warera_data.get('infos', {})
            for warera_field, db_key, _ in CONGO_LOCAL_ROLES:
                if infos.get(warera_field) == CONGO_COUNTRY_ID:
                    qualified.setdefault(str(member.id), set()).add(db_key)

        # Second pass: strip government roles from anyone who currently holds one
        # but was not confirmed as a qualifying citizen above.
        removed = 0
        for _, db_key, display_name in CONGO_LOCAL_ROLES:
            role_id = config.get(db_key)
            if not role_id:
                continue
            discord_role = guild.get_role(int(role_id))
            if not discord_role:
                continue
            for m in list(discord_role.members):
                mid = str(m.id)
                if mid in api_failed:
                    continue  # Couldn't verify — leave role alone
                if db_key in qualified.get(mid, set()):
                    continue  # Verified they qualify — keep role
                # Not a tracked citizen, or citizen without this WarEra role
                try:
                    await m.remove_roles(
                        discord_role, reason=f'Local role audit: does not qualify for Congo {display_name}'
                    )
                    removed += 1
                except discord.Forbidden:
                    pass

        parts = [f'✅ Synced Congolese government roles for **{updated}** citizen(s).']
        if removed:
            parts.append(f'🗑️ Removed unqualified role assignments from **{removed}** member(s).')
        if errors:
            parts.append(f'⚠️ Could not fetch WarEra data for **{errors}** member(s) (roles left unchanged).')
        await interaction.followup.send('\n'.join(parts), ephemeral=True)

    # ── /admin-diagnose-member ────────────────────────────────────────────────

    @app_commands.command(
        name='admin-diagnose-member',
        description='[Admin] Show raw WarEra data and local role sync result for a specific member.'
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member='The Discord member to diagnose.')
    async def admin_diagnose_member(self, interaction: discord.Interaction, member: discord.Member):
        if not await self._is_senate(interaction):
            await interaction.response.send_message('No permission.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        config = await self.bot.db.get_guild_config(str(guild.id)) or {}

        tracked = await self.bot.db.get_tracked_user(str(member.id), str(guild.id))
        lines = [f'**Diagnosis for {member.mention}**\n']

        # DB record
        if tracked:
            lines.append(
                f'**DB:** `assigned_role={tracked.get("assigned_role")}` | '
                f'`country_id={tracked.get("country_id")}` | '
                f'`warera_id={tracked.get("warera_id")}`'
            )
        else:
            lines.append('**DB:** ⚠️ Not found in `tracked_users`')
            await interaction.followup.send('\n'.join(lines), ephemeral=True)
            return

        # WarEra data
        warera_data = await get_user_lite(tracked['warera_id'])
        if not warera_data:
            lines.append('**WarEra:** ❌ API returned nothing for this warera_id')
            await interaction.followup.send('\n'.join(lines), ephemeral=True)
            return

        lines.append(
            f'**WarEra country:** `{warera_data.get("country")}`  '
            f'(Congo = `{CONGO_COUNTRY_ID}`)'
        )
        infos = warera_data.get('infos') or {}
        lines.append(f'**WarEra infos:** `{infos}`')

        # Per-role diagnosis
        lines.append('\n**Local role check:**')
        for warera_field, db_key, display_name in CONGO_LOCAL_ROLES:
            role_id = config.get(db_key)
            if not role_id:
                lines.append(f'  ⚙️ **{display_name}**: not configured in /setup')
                continue
            discord_role = guild.get_role(int(role_id))
            if not discord_role:
                lines.append(f'  ⚠️ **{display_name}**: role ID `{role_id}` no longer exists in Discord')
                continue
            field_value = infos.get(warera_field)
            has_warera_role = (field_value == CONGO_COUNTRY_ID)
            has_discord_role = discord_role in member.roles
            status = '✅' if has_warera_role == has_discord_role else '❌ mismatch'
            lines.append(
                f'  {status} **{display_name}**: '
                f'WarEra `{warera_field}`=`{field_value}` → has_role={has_warera_role} | '
                f'Discord role present={has_discord_role}'
            )

        await interaction.followup.send('\n'.join(lines), ephemeral=True)

    @app_commands.command(name='backup-db', description='[Admin] Force an immediate database backup.')
    @app_commands.default_permissions(administrator=True)
    async def backup_db(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.db.backup()
            await interaction.followup.send('✅ Database backed up successfully.', ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f'❌ Backup failed: {e}', ephemeral=True)


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
