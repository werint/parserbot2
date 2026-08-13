import discord
from discord.ext import commands, tasks
import asyncio
import re
from datetime import datetime, timedelta
import traceback
import sys
import os
from dotenv import load_dotenv

load_dotenv()

# НАСТРОЙКИ БОТА
TARGET_SERVER_ID = 1536815201905541293  # ОСНОВНОЙ СЕРВЕР (куда выдаём роли и баним)
LOG_CHANNEL_ID = 1536851779096944700    # Канал для логов

# КОНФИГУРАЦИЯ: сервер-источник -> список ролей для проверки
SOURCE_SERVERS = {
    1379837805366087710: [  # Сервер #1
        1396136669534621696,
        1381557998274478131,
        1379880312271671336,
        1379880183372447785,
        1379906654220456078,
        1471567668711653459,
        1379907394229899506
    ],
    1269934482044096533: [  # Сервер #2
        1269941326510690347,
        1269941327374585880,
        1269960238002602065,
        1350892590064603256,
        1269941342667280465
    ],
    1003525677640851496: [  # Сервер #3
        1481402373879365835
    ],
    848325149191307264: [   # Сервер #4
        1277918655639846912
    ],
    1150420551324672030: [  # Сервер #5 (НОВЫЙ)
        1150422789778591764,
        1251618206905405573
    ],
    1318937492858343474: [  # Сервер #6 (НОВЫЙ)
        1318951502491942955
    ]
}

# СООТВЕТСТВИЕ: сервер-источник -> какая роль выдаётся на основном сервере
TARGET_ROLE_MAPPING = {
    1379837805366087710: 1536868470447284234,  # Сервер #1 -> роль
    1269934482044096533: 1536869777774219401,  # Сервер #2 -> роль
    1003525677640851496: 1536868334346313848,  # Сервер #3 -> роль
    848325149191307264:  1536868392974422036,  # Сервер #4 -> роль
    1150420551324672030: 1537435028559241336,  # Сервер #5 -> роль (НОВАЯ)
    1318937492858343474: 1537435159757070457   # Сервер #6 -> роль (НОВАЯ)
}

# Настройка интентов
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.bans = True

bot = commands.Bot(command_prefix='!', intents=intents)

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
                    del self.banned_users[user_id]
        except Exception:
            pass

    async def check_user_roles(self, user_id):
        """Проверяет наличие ролей на всех серверах-источниках"""
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
            
            # Проверяем наличие ЛЮБОЙ роли из списка
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
        """Проверяет роли пользователя и синхронизирует"""
        try:
            target_server = bot.get_guild(TARGET_SERVER_ID)
            if not target_server:
                return False
            
            target_member = target_server.get_member(user_id)
            if not target_member:
                return False
            
            username = username or target_member.display_name
            
            # Проверяем права бота
            bot_member = target_server.get_member(bot.user.id)
            if not bot_member:
                return False
            
            # Проверяем роли на всех серверах-источниках
            role_check = await self.check_user_roles(user_id)
            
            actions_performed = []
            
            # Проходим по каждому серверу-источнику
            for source_server_id, has_source_role in role_check['server_roles'].items():
                target_role_id = TARGET_ROLE_MAPPING.get(source_server_id)
                if not target_role_id:
                    continue
                
                target_role = target_server.get_role(target_role_id)
                if not target_role:
                    continue
                
                # Проверяем, может ли бот управлять этой ролью
                if target_role >= bot_member.top_role:
                    continue
                
                has_target_role = target_role in target_member.roles
                
                # Если есть роль на сервере-источнике, но нет на основном -> выдаём
                if has_source_role and not has_target_role:
                    try:
                        await target_member.add_roles(target_role, reason=f"Есть роль на сервере {source_server_id}")
                        actions_performed.append(f"✅ Выдана роль {target_role.name}")
                    except Exception:
                        pass
                
                # Если нет роли на сервере-источнике, но есть на основном -> забираем
                elif not has_source_role and has_target_role:
                    try:
                        await target_member.remove_roles(target_role, reason=f"Нет роли на сервере {source_server_id}")
                        actions_performed.append(f"🗑️ Удалена роль {target_role.name}")
                    except Exception:
                        pass
            
            # Логируем действия
            if actions_performed:
                log_msg = (
                    f"🔧 **Синхронизация**\n"
                    f"• Пользователь: `{username}`\n"
                    f"• ID: `{user_id}`\n"
                    f"• Действия: {', '.join(actions_performed)}"
                )
                await self.log_to_channel(log_msg, color=0x0099ff)
            
            # БАН: если нет ролей НИ НА ОДНОМ сервере-источнике
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
        
        # Информация о серверах-источниках
        for server_id, has_role in role_check['server_roles'].items():
            server = bot.get_guild(server_id)
            server_name = server.name if server else "Недоступен"
            report += f"• {server_name} (`{server_id}`): {'✅ Есть роль' if has_role else '❌ Нет роли'}\n"
        
        report += f"\n**Целевой сервер ({TARGET_SERVER_ID}):**\n"
        
        # Информация о целевых ролях
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
    
    # Подсчёт пользователей с каждой ролью
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
    """Показать все серверы, где есть бот"""
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
        
        # Проверяем права бота на сервере
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

# Запуск бота
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