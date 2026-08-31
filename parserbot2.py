import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import re
from datetime import datetime, timedelta
import traceback
import sys
import os
from dotenv import load_dotenv

load_dotenv()

TARGET_SERVER_ID = 1543991245594955816
LOG_CHANNEL_ID = 1543993492294864966
OWNER_ID = 427922282959077386

SOURCE_SERVERS = {
    1269934482044096533: [
        1269941326510690347,
        1269941327374585880,
        1269960238002602065,
        1350892590064603256,
        1269941342667280465
    ],
    1003525677640851496: [
        1481402373879365835
    ]
}

TARGET_ROLE_MAPPING = {
    1269934482044096533: 1543991299529777303,
    1003525677640851496: 1543991403506442260
}

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.bans = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

class AddRoleModal(discord.ui.Modal, title="Добавить отслеживаемую роль"):
    target_role_id = discord.ui.TextInput(
        label="ID роли на основном сервере",
        placeholder="Введите ID роли, которая уже есть на сервере...",
        required=True,
        max_length=20
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await add_role(interaction, self.target_role_id.value)

class RemoveRoleModal(discord.ui.Modal, title="Удалить отслеживаемую роль"):
    role_id = discord.ui.TextInput(
        label="ID роли для удаления",
        placeholder="Введите ID роли из списка...",
        required=True,
        max_length=20
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await remove_role(interaction, self.role_id.value)

class SourceServerModal(discord.ui.Modal, title="Введите ID сервера-источника"):
    server_id = discord.ui.TextInput(
        label="ID сервера-источника",
        placeholder="Введите ID сервера из списка...",
        required=True,
        max_length=20
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await add_role_with_source(interaction, self.server_id.value)

class ControlPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="⚙️ Настройка сервера", style=discord.ButtonStyle.primary, custom_id="setup_btn", row=0)
    async def setup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await setup_server(interaction)
    
    @discord.ui.button(label="➕ Добавить роль", style=discord.ButtonStyle.success, custom_id="add_role_btn", row=0)
    async def add_role_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AddRoleModal()
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="🗑️ Удалить роль", style=discord.ButtonStyle.danger, custom_id="remove_role_btn", row=0)
    async def remove_role_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RemoveRoleModal()
        await interaction.response.send_modal(modal)

class UnbanButton(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label='🔓 Разблокировать', style=discord.ButtonStyle.green, custom_id='unban_button')
    async def unban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            target_server = bot.get_guild(TARGET_SERVER_ID)
            user = await bot.fetch_user(self.user_id)
            await target_server.unban(user, reason="Разблокировка через кнопку")
            
            embed = discord.Embed(
                description=(
                    f"✅ **Пользователь разблокирован**\n"
                    f"• Пользователь: `{user.display_name}`\n"
                    f"• ID: `{self.user_id}`\n"
                    f"• Разблокировал: {interaction.user.mention}\n"
                    f"• Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                ),
                color=0x00ff00,
                timestamp=datetime.now()
            )
            await interaction.response.edit_message(embed=embed, view=None)
            await role_bot.log_to_channel(
                f"🔓 **Разблокировка через кнопку**\n"
                f"• Пользователь: `{user.display_name}`\n"
                f"• ID: `{self.user_id}`\n"
                f"• Администратор: {interaction.user.mention}",
                color=0x00ff00
            )
            if self.user_id in role_bot.banned_users:
                del role_bot.banned_users[self.user_id]
        except discord.NotFound:
            await interaction.response.send_message("❌ Пользователь не забанен или уже разбанен", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Нет прав для разблокировки", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

class RoleSyncBot:
    def __init__(self):
        self.is_monitoring = False
        self.start_time = datetime.now()
        self.banned_users = {}
        self.last_check = datetime.now()

    async def log_to_channel(self, message, color=0x00ff00, view=None):
        try:
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                embed = discord.Embed(description=message, color=color, timestamp=datetime.now())
                await channel.send(embed=embed, view=view)
        except Exception:
            pass

    async def ban_user(self, user_id, username, reason="Нет ролей на исходных серверах"):
        try:
            target_server = bot.get_guild(TARGET_SERVER_ID)
            user = await bot.fetch_user(user_id)
            ban_duration = timedelta(minutes=10)
            ban_reason = f"{reason} | Автобан до {(datetime.now() + ban_duration).strftime('%d.%m.%Y %H:%M')}"
            await target_server.ban(user, reason=ban_reason, delete_message_days=0)
            
            ban_embed = discord.Embed(
                description=(
                    f"🔨 **Пользователь заблокирован**\n"
                    f"• Имя: `{username}`\n"
                    f"• Упоминание: <@{user_id}>\n"
                    f"• Профиль: [Перейти](https://discord.com/users/{user_id})\n\n"
                    f"**Причина:**\n"
                    f"• Нет ролей ни на одном исходном сервере\n\n"
                    f"**Статус:**\n"
                    f"• Бан на 10 минут\n"
                    f"• Авторазбан: {(datetime.now() + ban_duration).strftime('%d.%m.%Y %H:%M')}"
                ),
                color=0xff0000,
                timestamp=datetime.now()
            )
            
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                await channel.send(embed=ban_embed, view=UnbanButton(user_id))
            
            self.banned_users[user_id] = datetime.now()
            return True
        except Exception as e:
            await self.log_to_channel(f"❌ Ошибка бана `{username}`: {e}", color=0xff0000)
            return False

    async def auto_unban_users(self):
        try:
            target_server = bot.get_guild(TARGET_SERVER_ID)
            if not target_server:
                return
            
            current_time = datetime.now()
            users_to_unban = []
            
            for user_id, ban_time in list(self.banned_users.items()):
                if (current_time - ban_time).total_seconds() >= 600:
                    users_to_unban.append(user_id)
            
            for user_id in users_to_unban:
                try:
                    user = await bot.fetch_user(user_id)
                    await target_server.unban(user, reason="Автоматический разбан после 10 минут")
                    del self.banned_users[user_id]
                    await self.log_to_channel(
                        f"🔓 **Автоматический разбан**\n• Пользователь: `{user.display_name}`\n• ID: `{user_id}`",
                        color=0x00ff00
                    )
                except:
                    if user_id in self.banned_users:
                        del self.banned_users[user_id]
        except Exception:
            pass

    async def check_user_roles(self, user_id):
        result = {}
        has_any_roles = False
        
        for source_server_id, role_ids in SOURCE_SERVERS.items():
            server = bot.get_guild(source_server_id)
            if not server:
                result[source_server_id] = False
                continue
            
            member = server.get_member(user_id)
            if not member:
                result[source_server_id] = False
                continue
            
            has_role = False
            for role_id in role_ids:
                role = server.get_role(role_id)
                if role and role in member.roles:
                    has_role = True
                    has_any_roles = True
                    break
            
            result[source_server_id] = has_role
        
        return {
            'server_roles': result,
            'has_any_roles': has_any_roles
        }

    async def check_and_sync_user(self, user_id, username=None, check_ban=True):
        try:
            target_server = bot.get_guild(TARGET_SERVER_ID)
            if not target_server:
                return False
            
            target_member = target_server.get_member(user_id)
            if not target_member:
                return False
            
            username = username or target_member.display_name
            
            bot_member = target_server.get_member(bot.user.id)
            if not bot_member:
                return False
            
            role_check = await self.check_user_roles(user_id)
            
            actions_performed = []
            
            for source_server_id, has_source_role in role_check['server_roles'].items():
                target_role_id = TARGET_ROLE_MAPPING.get(source_server_id)
                if not target_role_id:
                    continue
                
                target_role = target_server.get_role(target_role_id)
                if not target_role:
                    continue
                
                if target_role >= bot_member.top_role:
                    continue
                
                has_target_role = target_role in target_member.roles
                
                if has_source_role and not has_target_role:
                    try:
                        await target_member.add_roles(target_role, reason=f"Есть роль на сервере {source_server_id}")
                        actions_performed.append(f"✅ Выдана роль {target_role.name}")
                    except Exception:
                        pass
                
                elif not has_source_role and has_target_role:
                    try:
                        await target_member.remove_roles(target_role, reason=f"Нет роли на сервере {source_server_id}")
                        actions_performed.append(f"🗑️ Удалена роль {target_role.name}")
                    except Exception:
                        pass
            
            if actions_performed:
                log_msg = (
                    f"🔧 **Синхронизация**\n"
                    f"• Пользователь: `{username}`\n"
                    f"• ID: `{user_id}`\n"
                    f"• Действия: {', '.join(actions_performed)}"
                )
                await self.log_to_channel(log_msg, color=0x0099ff)
            
            if check_ban and not role_check['has_any_roles']:
                if user_id not in self.banned_users:
                    if bot_member.guild_permissions.ban_members:
                        await self.ban_user(user_id, username)
                        return True
            
            return len(actions_performed) > 0
            
        except Exception:
            return False

    async def parse_snitch_message(self, message):
        try:
            content = message.content
            if "Потеря ролей:" in content and "Участник лишён необходимых ролей" in content:
                name_match = re.search(r"Имя:\s*(.+)", content)
                mention_match = re.search(r"Упоминание:\s*(<@!?(\d+)>)", content)
                
                if name_match and mention_match:
                    username = name_match.group(1).strip()
                    user_id = mention_match.group(2)
                    await self.check_and_sync_user(int(user_id), username, check_ban=True)
        except Exception:
            pass

role_bot = RoleSyncBot()

async def setup_server(interaction: discord.Interaction):
    try:
        guild = interaction.guild
        
        if guild.id != TARGET_SERVER_ID:
            await interaction.followup.send("❌ Эта команда доступна только на основном сервере!", ephemeral=True)
            return
        
        existing_main = discord.utils.get(guild.categories, name="MAIN")
        existing_high = discord.utils.get(guild.categories, name="HIGH")
        
        if existing_main and existing_high:
            await interaction.followup.send("⚠️ Категории уже существуют! Пропускаю создание.", ephemeral=True)
            return
        
        main_category = await guild.create_category(name="MAIN")
        high_category = await guild.create_category(name="HIGH")
        
        base_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False)
        }
        
        news = await main_category.create_text_channel(name="news", overwrites=base_overwrites)
        flood = await main_category.create_text_channel(name="flood", overwrites=base_overwrites)
        tags = await main_category.create_text_channel(name="tags", overwrites=base_overwrites)
        media = await main_category.create_text_channel(name="media", overwrites=base_overwrites)
        logs = await high_category.create_text_channel(name="logs", overwrites=base_overwrites)
        high_flood = await high_category.create_text_channel(name="high-flood", overwrites=base_overwrites)
        
        voice_channels = []
        for i in range(1, 5):
            voice = await main_category.create_voice_channel(name=f"voice {i}", overwrites=base_overwrites)
            voice_channels.append(voice)
        
        high_voice = await high_category.create_voice_channel(name="high-voice", overwrites=base_overwrites)
        
        embed = discord.Embed(
            title="✅ Сервер настроен!",
            description="Все каналы и категории созданы.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="📁 Категория MAIN",
            value=f"{news.mention} {flood.mention} {tags.mention} {media.mention}\n" + " ".join([vc.mention for vc in voice_channels]),
            inline=False
        )
        embed.add_field(
            name="📁 Категория HIGH",
            value=f"{logs.mention} {high_flood.mention} {high_voice.mention}",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка: {str(e)[:100]}", ephemeral=True)

async def add_role(interaction: discord.Interaction, target_role_id: str):
    try:
        guild = interaction.guild
        
        if guild.id != TARGET_SERVER_ID:
            await interaction.followup.send("❌ Эта команда доступна только на основном сервере!", ephemeral=True)
            return
        
        if not target_role_id.isdigit():
            await interaction.followup.send("❌ ID должен быть числом", ephemeral=True)
            return
        
        target_role_id_int = int(target_role_id)
        
        for source_id, t_id in TARGET_ROLE_MAPPING.items():
            if t_id == target_role_id_int:
                await interaction.followup.send("❌ Эта роль уже отслеживается!", ephemeral=True)
                return
        
        target_role = guild.get_role(target_role_id_int)
        if not target_role:
            await interaction.followup.send("❌ Роль не найдена на сервере!", ephemeral=True)
            return
        
        source_servers_list = "\n".join([f"`{s_id}` - {bot.get_guild(s_id).name if bot.get_guild(s_id) else 'Недоступен'}" for s_id in SOURCE_SERVERS.keys()])
        
        embed = discord.Embed(
            title="🔍 Выберите сервер-источник",
            description=f"Роль `{target_role.name}` будет связана с одним из серверов:\n\n{source_servers_list}\n\nВведите ID сервера в следующем окне.",
            color=discord.Color.blue()
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        modal = SourceServerModal()
        await interaction.followup.send_modal(modal)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка: {str(e)[:100]}", ephemeral=True)

async def add_role_with_source(interaction: discord.Interaction, source_server_id: str):
    try:
        guild = interaction.guild
        
        if not source_server_id.isdigit():
            await interaction.followup.send("❌ ID сервера должен быть числом", ephemeral=True)
            return
        
        source_server_id_int = int(source_server_id)
        
        if source_server_id_int not in SOURCE_SERVERS:
            await interaction.followup.send("❌ Сервер не найден в списке доступных!", ephemeral=True)
            return
        
        if source_server_id_int in TARGET_ROLE_MAPPING:
            await interaction.followup.send("❌ Этот сервер уже привязан к другой роли!", ephemeral=True)
            return
        
        target_role = guild.get_role(int(interaction.message.content))
        if not target_role:
            await interaction.followup.send("❌ Роль не найдена!", ephemeral=True)
            return
        
        TARGET_ROLE_MAPPING[source_server_id_int] = target_role.id
        
        main_category = discord.utils.get(guild.categories, name="MAIN")
        high_category = discord.utils.get(guild.categories, name="HIGH")
        
        if main_category:
            await main_category.set_permissions(target_role, view_channel=True)
        if high_category:
            await high_category.set_permissions(target_role, view_channel=True)
        
        for channel in guild.channels:
            if isinstance(channel, discord.TextChannel):
                if channel.category and channel.category.name in ["MAIN", "HIGH"]:
                    await channel.set_permissions(target_role, view_channel=True, read_messages=True)
        
        for channel in guild.channels:
            if isinstance(channel, discord.VoiceChannel):
                if channel.category and channel.category.name in ["MAIN", "HIGH"]:
                    await channel.set_permissions(target_role, view_channel=True, connect=True)
        
        source_guild = bot.get_guild(source_server_id_int)
        source_roles = SOURCE_SERVERS[source_server_id_int]
        
        embed = discord.Embed(
            title="✅ Роль добавлена!",
            color=discord.Color.green()
        )
        embed.add_field(name="Сервер-источник", value=source_guild.name if source_guild else str(source_server_id_int), inline=True)
        embed.add_field(name="Роли-источники", value=f"`{', '.join(map(str, source_roles))}`", inline=True)
        embed.add_field(name="Целевая роль", value=target_role.mention, inline=False)
        embed.add_field(name="Доступ к каналам", value="✅ Настроен", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        await role_bot.log_to_channel(
            f"➕ **Добавлена новая роль**\n"
            f"• Сервер-источник: `{source_guild.name if source_guild else source_server_id}` (`{source_server_id}`)\n"
            f"• Роли-источники: `{', '.join(map(str, source_roles))}`\n"
            f"• Целевая роль: {target_role.mention}",
            color=0x00ff00
        )
        
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка: {str(e)[:100]}", ephemeral=True)

async def remove_role(interaction: discord.Interaction, role_id: str):
    try:
        guild = interaction.guild
        
        if guild.id != TARGET_SERVER_ID:
            await interaction.followup.send("❌ Эта команда доступна только на основном сервере!", ephemeral=True)
            return
        
        if not role_id.isdigit():
            await interaction.followup.send("❌ ID должен быть числом", ephemeral=True)
            return
        
        role_id_int = int(role_id)
        
        source_server_id = None
        for s_id, t_id in TARGET_ROLE_MAPPING.items():
            if t_id == role_id_int:
                source_server_id = s_id
                break
        
        if not source_server_id:
            await interaction.followup.send("❌ Роль не найдена в отслеживании", ephemeral=True)
            return
        
        target_role = guild.get_role(role_id_int)
        
        del TARGET_ROLE_MAPPING[source_server_id]
        
        if target_role:
            try:
                await target_role.delete(reason="Удалена из отслеживания")
                role_deleted = "✅ Роль удалена с сервера"
            except:
                role_deleted = "⚠️ Не удалось удалить роль (возможно, она используется)"
        else:
            role_deleted = "ℹ️ Роль не найдена на сервере"
        
        embed = discord.Embed(
            title="✅ Роль удалена из отслеживания!",
            color=discord.Color.green()
        )
        embed.add_field(name="Статус", value=role_deleted, inline=False)
        embed.add_field(name="Сервер-источник", value=f"`{source_server_id}`", inline=True)
        embed.add_field(name="Целевая роль", value=f"`{role_id}`", inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        await role_bot.log_to_channel(
            f"🗑️ **Роль удалена из отслеживания**\n"
            f"• Сервер-источник: `{source_server_id}`\n"
            f"• Целевая роль: `{role_id}`",
            color=0xff0000
        )
        
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="souz", description="Панель управления ботом")
async def souz_command(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ У вас нет прав на использование этой команды!", ephemeral=True)
        return
    
    if interaction.guild.id != TARGET_SERVER_ID:
        await interaction.response.send_message("❌ Эта команда доступна только на основном сервере!", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=False)
    await asyncio.sleep(0.1)
    
    embed = discord.Embed(
        title="🤝 ДОБРО ПОЖАЛОВАТЬ В СОЮЗНЫЙ БОТ!",
        description="Бот для управления доступом на основе ролей с других серверов",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="📋 Информация",
        value=f"**Основной сервер:** <#{TARGET_SERVER_ID}>\n"
              f"**Серверов-источников:** {len(SOURCE_SERVERS)}\n"
              f"**Отслеживаемых ролей:** {len(TARGET_ROLE_MAPPING)}",
        inline=False
    )
    
    view = ControlPanelView()
    await interaction.followup.send(embed=embed, view=view)

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user.name} запущен!')
    print(f'🎯 Основной сервер: {TARGET_SERVER_ID}')
    print(f'📋 Канал логов: {LOG_CHANNEL_ID}')
    
    print(f'\n🔍 Серверы-источники:')
    for server_id in SOURCE_SERVERS.keys():
        server = bot.get_guild(server_id)
        status = "✅" if server else "❌"
        print(f'   {server_id}: {status}')
    
    print(f'\n🎯 Целевые роли:')
    for source_id, target_id in TARGET_ROLE_MAPPING.items():
        target_server = bot.get_guild(TARGET_SERVER_ID)
        role = target_server.get_role(target_id) if target_server else None
        role_name = role.name if role else "Не найдена"
        print(f'   {source_id} -> {role_name} ({target_id})')
    
    try:
        await bot.tree.sync()
        print('✅ Команды синхронизированы')
    except Exception as e:
        print(f'⚠️ Ошибка синхронизации команд: {e}')
    
    activity = discord.Activity(type=discord.ActivityType.watching, name=f"{len(SOURCE_SERVERS)} серверов | 3 сек")
    await bot.change_presence(activity=activity)
    
    await load_banned_users()
    
    startup_msg = (
        f"🟢 **Role Sync Bot запущен**\n"
        f"• Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"• Серверов-источников: {len(SOURCE_SERVERS)}\n"
        f"• Интервал: 3 секунды\n"
        f"• Авторазбан: 10 минут"
    )
    await role_bot.log_to_channel(startup_msg, color=0x00ff00)
    
    role_bot.is_monitoring = True
    rapid_sync_task.start()
    auto_unban_task.start()
    
    await bot.wait_until_ready()
    await asyncio.sleep(5)
    await sync_all_users_once()

async def load_banned_users():
    try:
        target_server = bot.get_guild(TARGET_SERVER_ID)
        if target_server:
            bans = [entry async for entry in target_server.bans()]
            for ban_entry in bans:
                role_bot.banned_users[ban_entry.user.id] = datetime.now() - timedelta(minutes=5)
            print(f"📋 Загружено {len(bans)} забаненных пользователей")
    except Exception as e:
        print(f"❌ Ошибка загрузки банов: {e}")

async def sync_all_users_once():
    try:
        target_server = bot.get_guild(TARGET_SERVER_ID)
        if not target_server:
            return
        
        members = [member for member in target_server.members if not member.bot]
        total_count = len(members)
        
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🔄 **Проверка всех {total_count} пользователей...**")
        
        processed = 0
        actions = 0
        
        for member in members:
            processed += 1
            result = await role_bot.check_and_sync_user(member.id, check_ban=True)
            if result:
                actions += 1
            
            await asyncio.sleep(0.02)
        
        if log_channel:
            await log_channel.send(f"✅ **Проверка завершена!**\n• Проверено: {processed}\n• Действий: {actions}")
        
    except Exception as e:
        print(f"❌ Ошибка проверки: {e}")

@tasks.loop(seconds=3)
async def rapid_sync_task():
    try:
        await sync_all_users()
    except Exception:
        pass

@tasks.loop(minutes=1)
async def auto_unban_task():
    try:
        await role_bot.auto_unban_users()
    except Exception:
        pass

async def sync_all_users():
    try:
        target_server = bot.get_guild(TARGET_SERVER_ID)
        if not target_server:
            return
        
        for member in target_server.members:
            if member.bot:
                continue
            await role_bot.check_and_sync_user(member.id, check_ban=True)
            await asyncio.sleep(0.02)
    except Exception:
        pass

@bot.event
async def on_message(message):
    try:
        if message.author == bot.user:
            return
        
        if message.channel.id == LOG_CHANNEL_ID:
            await role_bot.parse_snitch_message(message)
        
        await bot.process_commands(message)
    except Exception:
        pass

@bot.command(name='check_user')
@commands.has_permissions(administrator=True)
async def check_user_command(ctx, user: discord.Member = None):
    if not user:
        user = ctx.author
    
    await ctx.send(f"🔍 Проверяю {user.mention}...")
    
    try:
        role_check = await role_bot.check_user_roles(user.id)
        
        target_server = bot.get_guild(TARGET_SERVER_ID)
        
        report = (
            f"📋 **Отчет по пользователю {user.mention}**\n"
            f"• ID: `{user.id}`\n"
            f"• Имя: `{user.display_name}`\n\n"
            f"**Исходные сервера:**\n"
        )
        
        for server_id, has_role in role_check['server_roles'].items():
            server = bot.get_guild(server_id)
            server_name = server.name if server else "Недоступен"
            report += f"• {server_name} (`{server_id}`): {'✅ Есть роль' if has_role else '❌ Нет роли'}\n"
        
        report += f"\n**Целевой сервер ({TARGET_SERVER_ID}):**\n"
        
        for source_id, target_role_id in TARGET_ROLE_MAPPING.items():
            target_role = target_server.get_role(target_role_id)
            if target_role:
                has_role = target_role in user.roles
                report += f"• {target_role.name}: {'✅ Есть' if has_role else '❌ Нет'}\n"
        
        report += f"\n**Статус бана:** {'🔨 Забанен' if user.id in role_bot.banned_users else '✅ Не забанен'}"
        
        if user.id in role_bot.banned_users:
            ban_time = role_bot.banned_users[user.id]
            time_remaining = timedelta(minutes=10) - (datetime.now() - ban_time)
            if time_remaining.total_seconds() > 0:
                minutes = int(time_remaining.total_seconds() // 60)
                seconds = int(time_remaining.total_seconds() % 60)
                report += f"\n• До разбана: {minutes}м {seconds}с"
        
        await ctx.send(report)
        
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")

@bot.command(name='stats')
@commands.has_permissions(administrator=True)
async def stats_command(ctx):
    target_server = bot.get_guild(TARGET_SERVER_ID)
    if not target_server:
        await ctx.send("❌ Целевой сервер не доступен")
        return
    
    total_members = len([m for m in target_server.members if not m.bot])
    banned_count = len(role_bot.banned_users)
    
    role_stats = {}
    for target_role_id in TARGET_ROLE_MAPPING.values():
        role = target_server.get_role(target_role_id)
        if role:
            count = len([m for m in target_server.members if role in m.roles])
            role_stats[role.name] = count
    
    stats_msg = (
        f"📊 **Статистика**\n"
        f"• Время работы: {datetime.now() - role_bot.start_time}\n"
        f"• Всего пользователей: {total_members}\n"
        f"• Забанено: {banned_count}\n"
        f"• Серверов-источников: {len(SOURCE_SERVERS)}\n"
        f"• Интервал: 3 секунды\n\n"
        f"**Роли на основном сервере:**\n"
    )
    
    for role_name, count in role_stats.items():
        stats_msg += f"• {role_name}: {count} пользователей\n"
    
    await ctx.send(stats_msg)

@bot.command(name='sync_now')
@commands.has_permissions(administrator=True)
async def sync_now_command(ctx):
    await ctx.send("⚡ Запускаю синхронизацию...")
    
    try:
        target_server = bot.get_guild(TARGET_SERVER_ID)
        if not target_server:
            await ctx.send("❌ Целевой сервер не доступен")
            return
        
        members = [member for member in target_server.members if not member.bot]
        total_count = len(members)
        
        status_msg = await ctx.send(f"🔍 Обработка {total_count} пользователей...")
        
        processed = 0
        actions = 0
        
        for member in members:
            processed += 1
            result = await role_bot.check_and_sync_user(member.id, check_ban=True)
            if result:
                actions += 1
            
            if processed % 10 == 0:
                await status_msg.edit(content=f"⚡ {processed}/{total_count} ({actions} действий)")
            
            await asyncio.sleep(0.02)
        
        await status_msg.edit(
            content=f"✅ **Готово!**\n• Обработано: {processed}\n• Действий: {actions}"
        )
        
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")

@bot.command(name='check_bans')
@commands.has_permissions(administrator=True)
async def check_bans(ctx):
    try:
        target_server = bot.get_guild(TARGET_SERVER_ID)
        if not target_server:
            await ctx.send("❌ Целевой сервер не доступен")
            return
        
        current_time = datetime.now()
        ban_list = []
        
        for user_id, ban_time in role_bot.banned_users.items():
            try:
                user = await bot.fetch_user(user_id)
                time_passed = current_time - ban_time
                time_remaining = timedelta(minutes=10) - time_passed
                
                if time_remaining.total_seconds() > 0:
                    minutes_remaining = int(time_remaining.total_seconds() // 60)
                    seconds_remaining = int(time_remaining.total_seconds() % 60)
                    ban_list.append(f"• {user.display_name} - {minutes_remaining}м {seconds_remaining}с")
                else:
                    ban_list.append(f"• {user.display_name} - ожидает разбана")
            except Exception:
                ban_list.append(f"• ID {user_id} - пользователь не найден")
        
        if ban_list:
            await ctx.send(f"🔨 **Забаненные пользователи ({len(ban_list)}):**\n" + "\n".join(ban_list[:15]))
        else:
            await ctx.send("✅ Нет забаненных пользователей")
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")

@bot.command(name='servers')
@commands.has_permissions(administrator=True)
async def list_servers_command(ctx):
    servers = bot.guilds
    
    embed = discord.Embed(
        title="📊 Серверы бота",
        color=0x0099ff,
        timestamp=datetime.now()
    )
    
    for server in servers:
        is_target = "⭐ ОСНОВНОЙ" if server.id == TARGET_SERVER_ID else ""
        is_source = "📌 ИСТОЧНИК" if server.id in SOURCE_SERVERS else ""
        is_configured = "✅" if server.id in SOURCE_SERVERS or server.id == TARGET_SERVER_ID else "❌"
        
        bot_member = server.get_member(bot.user.id)
        if bot_member:
            can_manage_roles = "✅" if bot_member.guild_permissions.manage_roles else "❌"
            can_ban = "✅" if bot_member.guild_permissions.ban_members else "❌"
        else:
            can_manage_roles = "❌"
            can_ban = "❌"
        
        embed.add_field(
            name=f"{server.name}",
            value=f"ID: `{server.id}`\n"
                  f"Участников: {server.member_count}\n"
                  f"Статус: {is_configured} {is_target} {is_source}\n"
                  f"Управление ролями: {can_manage_roles}\n"
                  f"Бан: {can_ban}",
            inline=False
        )
    
    await ctx.send(embed=embed)

def main():
    print("🚀 Запуск Role Sync Bot...")
    print("=" * 50)
    print(f"🎯 Основной сервер: {TARGET_SERVER_ID}")
    print(f"📋 Канал логов: {LOG_CHANNEL_ID}")
    print(f"🔍 Серверов-источников: {len(SOURCE_SERVERS)}")
    print("=" * 50)
    
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ Ошибка: DISCORD_TOKEN не найден")
        return
    
    try:
        bot.run(token)
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()