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

# Настройки бота
SOURCE_SERVER_ID = 1003525677640851496  # Первый сервер-источник
SOURCE_SERVER_2_ID = 1165977084099842098  # Второй сервер-источник
TARGET_SERVER_ID = 1457337712851026067  # Целевой сервер (куда выдаём роли)

# Роли для проверки на первом сервере (сервер #1)
SOURCE_ROLE_IDS = [
    1352527374515699712,
    1383426539886084267,  
    1317882573342507069,
    1381685630555258931,
    1381683377090068550,
    1381682246678741022,
    1310673963000528949,
    1223589384452833290
]

# Роли для проверки на втором сервере (сервер #2)
SOURCE_2_ROLE_IDS = [
    1446859389939220542  # Только одна роль для второго сервера
]

# Целевые роли для выдачи (на целевом сервере)
TARGET_ROLE_ID = 1457339761395105833    # Роль за сервер #1
TARGET_ROLE_2_ID = 1457339829607071874  # Роль за сервер #2

LOG_CHANNEL_ID = 1437338399206805625    # Канал для логов (оставляем прежний)

# Настройка интентов
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.bans = True

bot = commands.Bot(command_prefix='!', intents=intents)

class UnbanButton(discord.ui.View):
    """Кнопка для разблокировки пользователя"""
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
            await interaction.response.send_message(f"❌ Ошибка при разблокировки: {e}", ephemeral=True)

class RoleSyncBot:
    def __init__(self):
        self.is_monitoring = False
        self.start_time = datetime.now()
        self.banned_users = {}  # Теперь храним время бана {user_id: ban_time}
        self.last_check = datetime.now()

    async def log_to_channel(self, message, color=0x00ff00, view=None):
        """Отправляет лог в указанный канал"""
        try:
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                embed = discord.Embed(
                    description=message,
                    color=color,
                    timestamp=datetime.now()
                )
                await channel.send(embed=embed, view=view)
            else:
                print(f"Не удалось найти канал логов: {LOG_CHANNEL_ID}")
        except Exception as e:
            print(f"Ошибка при отправке лога: {e}")

    async def ban_user(self, user_id, username, reason="Отсутствие требуемых ролей на всех серверах"):
        """Банит пользователя на 10 минут"""
        try:
            target_server = bot.get_guild(TARGET_SERVER_ID)
            user = await bot.fetch_user(user_id)
            
            # Баним на 10 минут
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
                    f"• Участник лишён необходимых ролей на всех серверах\n\n"
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
            
            # Сохраняем время бана
            self.banned_users[user_id] = datetime.now()
            print(f"🔨 Забанен пользователь {username} ({user_id}) на 10 минут")
            
            return True
            
        except discord.Forbidden:
            error_msg = f"❌ Нет прав для бана пользователя `{username}`"
            await self.log_to_channel(error_msg, color=0xff0000)
        except discord.NotFound:
            error_msg = f"❌ Пользователь `{username}` не найден"
            await self.log_to_channel(error_msg, color=0xff0000)
        except Exception as e:
            error_msg = f"❌ Ошибка при бане пользователя `{username}`: {e}"
            await self.log_to_channel(error_msg, color=0xff0000)
        
        return False

    async def auto_unban_users(self):
        """Автоматически разбанивает пользователей после 10 минут"""
        try:
            target_server = bot.get_guild(TARGET_SERVER_ID)
            if not target_server:
                return
            
            current_time = datetime.now()
            users_to_unban = []
            
            # Проверяем всех забаненных пользователей
            for user_id, ban_time in list(self.banned_users.items()):
                ban_duration = current_time - ban_time
                
                # Если прошло больше 10 минут - разбаниваем
                if ban_duration.total_seconds() >= 600:  # 600 секунд = 10 минут
                    users_to_unban.append(user_id)
            
            # Разбаниваем пользователей
            for user_id in users_to_unban:
                try:
                    user = await bot.fetch_user(user_id)
                    await target_server.unban(user, reason="Автоматический разбан после 10 минут")
                    
                    # Удаляем из списка забаненных
                    del self.banned_users[user_id]
                    
                    log_msg = (
                        f"🔓 **Автоматический разбан**\n"
                        f"• Пользователь: `{user.display_name}`\n"
                        f"• ID: `{user_id}`\n"
                        f"• Бан длился: 10 минут\n"
                        f"• Время разбана: {current_time.strftime('%d.%m.%Y %H:%M:%S')}"
                    )
                    await self.log_to_channel(log_msg, color=0x00ff00)
                    print(f"🔓 Автоматически разбанен пользователь {user.display_name} ({user_id})")
                    
                except discord.NotFound:
                    # Пользователь уже разбанен или не найден
                    del self.banned_users[user_id]
                except Exception as e:
                    print(f"❌ Ошибка при авторазбане пользователя {user_id}: {e}")
            
            if users_to_unban:
                print(f"✅ Автоматически разбанено {len(users_to_unban)} пользователей")
                
        except Exception as e:
            print(f"❌ Ошибка в авторазбане: {e}")

    async def check_user_roles(self, user_id):
        """Проверяет роли пользователя на всех серверах"""
        try:
            source_server = bot.get_guild(SOURCE_SERVER_ID)
            source_server_2 = bot.get_guild(SOURCE_SERVER_2_ID)
            
            has_first_server_roles = False
            has_second_server_roles = False
            found_roles_first = []
            found_roles_second = []
            
            # Проверяем первый сервер (1003525677640851496)
            if source_server:
                source_member = source_server.get_member(user_id)
                if source_member:
                    for role_id in SOURCE_ROLE_IDS:
                        role = source_server.get_role(role_id)
                        if role and role in source_member.roles:
                            has_first_server_roles = True
                            found_roles_first.append(f"{role.name} ({role.id})")
            
            # Проверяем второй сервер (1165977084099842098)
            if source_server_2:
                source_member_2 = source_server_2.get_member(user_id)
                if source_member_2:
                    for role_id in SOURCE_2_ROLE_IDS:
                        role = source_server_2.get_role(role_id)
                        if role and role in source_member_2.roles:
                            has_second_server_roles = True
                            found_roles_second.append(f"{role.name} ({role.id})")
            
            has_any_roles = has_first_server_roles or has_second_server_roles
            
            return {
                'has_first_server': has_first_server_roles,
                'has_second_server': has_second_server_roles,
                'found_roles_first': found_roles_first,
                'found_roles_second': found_roles_second,
                'has_any_roles': has_any_roles
            }
            
        except Exception as e:
            print(f"❌ Ошибка при проверке ролей пользователя {user_id}: {e}")
            return {
                'has_first_server': False,
                'has_second_server': False,
                'found_roles_first': [],
                'found_roles_second': [],
                'has_any_roles': False
            }

    async def check_and_sync_user(self, user_id, username=None, check_ban=True):
        """Проверяет роли пользователя и синхронизирует"""
        try:
            target_server = bot.get_guild(TARGET_SERVER_ID)
            if not target_server:
                print("❌ Целевой сервер не найден")
                return False
            
            target_role = target_server.get_role(TARGET_ROLE_ID)
            target_role_2 = target_server.get_role(TARGET_ROLE_2_ID)
            
            if not target_role or not target_role_2:
                print("❌ Целевые роли не найдены")
                return False
            
            target_member = target_server.get_member(user_id)
            if not target_member:
                print(f"❌ Пользователь {user_id} не найден на целевом сервере")
                return False
            
            # Проверяем роли на всех серверах
            role_check = await self.check_user_roles(user_id)
            username = username or target_member.display_name
            
            has_target_role = target_role in target_member.roles
            has_target_role_2 = target_role_2 in target_member.roles
            
            actions_performed = []
            
            # Первая роль (сервер #1)
            if role_check['has_first_server'] and not has_target_role:
                try:
                    await target_member.add_roles(target_role, reason="Автоматическая синхронизация - сервер #1")
                    actions_performed.append("✅ Выдана роль за сервер #1")
                    print(f"✅ Выдана роль за сервер #1 пользователю {username} ({user_id})")
                except Exception as e:
                    print(f"❌ Ошибка при выдаче роли за сервер #1: {e}")
            elif not role_check['has_first_server'] and has_target_role:
                try:
                    await target_member.remove_roles(target_role, reason="Автоматическая синхронизация - нет ролей на сервере #1")
                    actions_performed.append("🗑️ Удалена роль за сервер #1")
                    print(f"🗑️ Удалена роль за сервер #1 у пользователя {username} ({user_id})")
                except Exception as e:
                    print(f"❌ Ошибка при удалении роли за сервер #1: {e}")
            
            # Вторая роль (сервер #2)
            if role_check['has_second_server'] and not has_target_role_2:
                try:
                    await target_member.add_roles(target_role_2, reason="Автоматическая синхронизация - сервер #2")
                    actions_performed.append("✅ Выдана роль за сервер #2")
                    print(f"✅ Выдана роль за сервер #2 пользователю {username} ({user_id})")
                except Exception as e:
                    print(f"❌ Ошибка при выдаче роли за сервер #2: {e}")
            elif not role_check['has_second_server'] and has_target_role_2:
                try:
                    await target_member.remove_roles(target_role_2, reason="Автоматическая синхронизация - нет ролей на сервере #2")
                    actions_performed.append("🗑️ Удалена роль за сервер #2")
                    print(f"🗑️ Удалена роль за сервер #2 у пользователя {username} ({user_id})")
                except Exception as e:
                    print(f"❌ Ошибка при удалении роли за сервер #2: {e}")
            
            # Логируем действия если они были
            if actions_performed:
                log_msg = (
                    f"🔧 **Синхронизация ролей**\n"
                    f"• Пользователь: `{username}`\n"
                    f"• ID: `{user_id}`\n"
                    f"• Сервер #1 (1003525677640851496): {'✅' if role_check['has_first_server'] else '❌'} {', '.join(role_check['found_roles_first']) if role_check['found_roles_first'] else 'Нет ролей'}\n"
                    f"• Сервер #2 (1165977084099842098): {'✅' if role_check['has_second_server'] else '❌'} {', '.join(role_check['found_roles_second']) if role_check['found_roles_second'] else 'Нет ролей'}\n"
                    f"• Действия: {', '.join(actions_performed)}"
                )
                await self.log_to_channel(log_msg, color=0x0099ff)
            
            # Логика бана: бан если нет ролей на исходных серверах
            if check_ban and not role_check['has_any_roles']:
                # Проверяем, есть ли у пользователя целевые роли
                has_any_target_role = has_target_role or has_target_role_2
                
                # Если есть целевые роли, но нет исходных ролей - бан
                if has_any_target_role:
                    print(f"⚠️ Пользователь {username} ({user_id}) имеет целевые роли, но нет исходных - подлежит бану")
                    
                    # Проверяем, не забанен ли уже пользователь
                    if user_id not in self.banned_users:
                        ban_result = await self.ban_user(user_id, username, "Отсутствие требуемых ролей на всех серверах")
                        if ban_result:
                            log_msg = (
                                f"🔨 **Пользователь забанен**\n"
                                f"• Пользователь: `{username}`\n"
                                f"• ID: `{user_id}`\n"
                                f"• Причина: Нет требуемых ролей ни на одном сервере\n"
                                f"• Имел целевые роли: {'Да' if has_any_target_role else 'Нет'}\n"
                                f"• Длительность: 10 минут"
                            )
                            await self.log_to_channel(log_msg, color=0xff6600)
                            return True
                    else:
                        print(f"ℹ️ Пользователь {username} ({user_id}) уже забанен, пропускаем")
                
                # Также баним пользователей без ЛЮБЫХ ролей (даже если нет целевых ролей)
                elif user_id not in self.banned_users:
                    # Пользователь на целевом сервере, но без целевых ролей
                    print(f"⚠️ Пользователь {username} ({user_id}) на целевом сервере, но без ролей - подлежит бану")
                    ban_result = await self.ban_user(user_id, username, "Нахождение на сервере без требуемых ролей")
                    if ban_result:
                        log_msg = (
                            f"🔨 **Пользователь забанен**\n"
                            f"• Пользователь: `{username}`\n"
                            f"• ID: `{user_id}`\n"
                            f"• Причина: Нахождение на сервере без требуемых ролей\n"
                            f"• Длительность: 10 минут"
                        )
                        await self.log_to_channel(log_msg, color=0xff6600)
                        return True
            
            return len(actions_performed) > 0
                
        except Exception as e:
            error_msg = f"❌ Критическая ошибка при синхронизации пользователя {user_id}: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
        
        return False

    async def parse_snitch_message(self, message):
        """Парсит сообщение от SnitchParser и выполняет действия"""
        try:
            content = message.content
            
            if "Потеря ролей:" in content and "Участник лишён необходимых ролей" in content:
                name_match = re.search(r"Имя:\s*(.+)", content)
                mention_match = re.search(r"Упоминание:\s*(<@!?(\d+)>)", content)
                
                if name_match:
                    username = name_match.group(1).strip()
                    user_id = mention_match.group(2) if mention_match else None
                    
                    if user_id:
                        await self.log_to_channel(
                            f"🔍 **Обнаружена потеря ролей**\n"
                            f"• Пользователь: `{username}`\n"
                            f"• ID: `{user_id}`\n"
                            f"• Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
                            color=0xff9900
                        )
                        
                        await self.check_and_sync_user(int(user_id), username, check_ban=True)
                    
        except Exception as e:
            error_msg = f"❌ Ошибка при парсинге сообщения: {e}"
            print(error_msg)

# Создаем экземпляр нашего бота
role_bot = RoleSyncBot()

@bot.event
async def on_ready():
    """Функция, которая выполняется при запуске бота"""
    print(f'✅ Бот {bot.user.name} успешно запущен!')
    print(f'📊 ID бота: {bot.user.id}')
    print(f'🕒 Время запуска: {datetime.now()}')
    
    # Проверяем доступность серверов
    source_server = bot.get_guild(SOURCE_SERVER_ID)
    source_server_2 = bot.get_guild(SOURCE_SERVER_2_ID)
    target_server = bot.get_guild(TARGET_SERVER_ID)
    
    print(f'🔍 Доступность серверов:')
    print(f'   Сервер #1 (1003525677640851496): {"✅" if source_server else "❌"}')
    print(f'   Сервер #2 (1165977084099842098): {"✅" if source_server_2 else "❌"}')
    print(f'   Целевой сервер (1457337712851026067): {"✅" if target_server else "❌"}')
    
    print(f'🔍 Проверка ролей:')
    print(f'   Сервер #1: проверяет {len(SOURCE_ROLE_IDS)} ролей')
    print(f'   Сервер #2: проверяет {len(SOURCE_2_ROLE_IDS)} ролей')
    print(f'   Целевой сервер: выдает 2 роли')
    
    activity = discord.Activity(type=discord.ActivityType.watching, name="2 сервера | 10 сек")
    await bot.change_presence(activity=activity)
    
    await load_banned_users()
    
    startup_msg = (
        f"🟢 **Role Sync Bot запущен**\n"
        f"• Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"• Статус: Мониторинг активен\n\n"
        f"**Конфигурация:**\n"
        f"• Сервер #1: {'✅' if source_server else '❌'} `1003525677640851496`\n"
        f"• Сервер #2: {'✅' if source_server_2 else '❌'} `1165977084099842098`\n"
        f"• Целевой сервер: {'✅' if target_server else '❌'} `1457337712851026067`\n\n"
        f"**Настройки:**\n"
        f"• Интервал проверки: `10 секунд`\n"
        f"• Авторазбан: `10 минут`\n"
        f"• Банит если: Нет ролей на исходных серверах\n"
        f"• Проверяемые роли на сервере #1: `{len(SOURCE_ROLE_IDS)}`\n"
        f"• Проверяемые роли на сервере #2: `{len(SOURCE_2_ROLE_IDS)}`"
    )
    await role_bot.log_to_channel(startup_msg, color=0x00ff00)
    
    role_bot.is_monitoring = True
    rapid_sync_task.start()
    unban_checker.start()
    auto_unban_task.start()
    
    # Запускаем проверку всех пользователей при старте
    await bot.wait_until_ready()
    await asyncio.sleep(10)  # Ждем загрузки всех членов
    await sync_all_users_once()

async def load_banned_users():
    """Загружает список забаненных пользователей при запуске"""
    try:
        target_server = bot.get_guild(TARGET_SERVER_ID)
        if target_server:
            bans = [entry async for entry in target_server.bans()]
            for ban_entry in bans:
                # При загрузке ставим текущее время минус 5 минут, чтобы не разбанивать сразу
                role_bot.banned_users[ban_entry.user.id] = datetime.now() - timedelta(minutes=5)
            print(f"📋 Загружено {len(bans)} забаненных пользователей")
    except Exception as e:
        print(f"❌ Ошибка при загрузке банов: {e}")

async def sync_all_users_once():
    """Проверяет всех пользователей один раз при запуске"""
    try:
        target_server = bot.get_guild(TARGET_SERVER_ID)
        if not target_server:
            print("❌ Целевой сервер не доступен для синхронизации")
            return
        
        members = [member for member in target_server.members if not member.bot]
        total_count = len(members)
        
        print(f"🔍 Начинаю проверку всех {total_count} пользователей на целевом сервере...")
        
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            progress_msg = await log_channel.send(
                f"🔄 **Начинаю проверку всех {total_count} пользователей...**"
            )
        else:
            progress_msg = None
        
        processed = 0
        actions = 0
        banned_count = 0
        
        for member in members:
            processed += 1
            result = await role_bot.check_and_sync_user(member.id, check_ban=True)
            if result:
                actions += 1
            
            # Считаем сколько пользователей забанено в этой сессии
            if member.id in role_bot.banned_users:
                banned_count += 1
            
            # Обновляем сообщение каждые 10 пользователей
            if progress_msg and processed % 10 == 0:
                try:
                    await progress_msg.edit(
                        content=f"🔄 **Проверка пользователей:** {processed}/{total_count}\n"
                               f"• Действий: {actions}\n"
                               f"• Новых банов: {banned_count}"
                    )
                except:
                    pass
            
            await asyncio.sleep(0.05)
        
        if progress_msg:
            await progress_msg.edit(
                content=f"✅ **Проверка завершена!**\n"
                       f"• Проверено: {processed}/{total_count} пользователей\n"
                       f"• Выполнено действий: {actions}\n"
                       f"• Забанено в этой сессии: {banned_count} пользователей"
            )
        
        print(f"✅ Проверено {processed} пользователей, выполнено действий: {actions}, забанено: {banned_count}")
        
    except Exception as e:
        print(f"❌ Ошибка при проверке всех пользователей: {e}")
        import traceback
        traceback.print_exc()

@tasks.loop(seconds=10)
async def rapid_sync_task():
    """Быстрая синхронизация всех пользователей каждые 10 секунд"""
    try:
        await sync_all_users()
    except Exception as e:
        print(f"❌ Ошибка в задаче синхронизации: {e}")

@tasks.loop(minutes=1)
async def unban_checker():
    """Проверяет истечение времени бана"""
    try:
        await role_bot.auto_unban_users()
    except Exception as e:
        print(f"❌ Ошибка в проверке банов: {e}")

@tasks.loop(minutes=1)
async def auto_unban_task():
    """Автоматический разбан каждую минуту"""
    try:
        await role_bot.auto_unban_users()
    except Exception as e:
        print(f"❌ Ошибка в авторазбане: {e}")

async def sync_all_users():
    """Синхронизирует всех пользователей на целевом сервере (для периодической проверки)"""
    try:
        target_server = bot.get_guild(TARGET_SERVER_ID)
        if not target_server:
            print("❌ Целевой сервер не доступен для синхронизации")
            return
        
        processed = 0
        actions = 0
        banned_in_cycle = 0
        
        for member in target_server.members:
            if member.bot:
                continue
                
            processed += 1
            result = await role_bot.check_and_sync_user(member.id, check_ban=True)
            if result:
                actions += 1
            
            # Считаем новые баны в этом цикле
            if member.id in role_bot.banned_users:
                banned_in_cycle += 1
            
            await asyncio.sleep(0.02)
        
        if actions > 0 or banned_in_cycle > 0:
            print(f"✅ Проверено {processed} пользователей, действий: {actions}, банов: {banned_in_cycle}")
        
    except Exception as e:
        print(f"❌ Ошибка при синхронизации всех пользователей: {e}")

@bot.event
async def on_message(message):
    try:
        if message.author == bot.user:
            return
        
        if message.channel.id == LOG_CHANNEL_ID:
            await role_bot.parse_snitch_message(message)
        
        await bot.process_commands(message)
    except Exception as e:
        print(f"Ошибка в on_message: {e}")

@bot.command(name='check_user')
@commands.has_permissions(administrator=True)
async def check_user_command(ctx, user: discord.Member = None):
    """Проверить конкретного пользователя (или себя)"""
    if not user:
        user = ctx.author
    
    await ctx.send(f"🔍 Проверяю пользователя {user.mention}...")
    
    try:
        # Получаем детальную информацию
        role_check = await role_bot.check_user_roles(user.id)
        
        # Проверяем синхронизацию
        result = await role_bot.check_and_sync_user(user.id, check_ban=True)
        
        # Получаем информацию о ролях на целевом сервере
        target_server = bot.get_guild(TARGET_SERVER_ID)
        target_role = target_server.get_role(TARGET_ROLE_ID)
        target_role_2 = target_server.get_role(TARGET_ROLE_2_ID)
        
        has_target_role = target_role in user.roles if target_role else False
        has_target_role_2 = target_role_2 in user.roles if target_role_2 else False
        
        # Создаем детальный отчет
        report = (
            f"📋 **Отчет по пользователю {user.mention}**\n"
            f"• ID: `{user.id}`\n"
            f"• Имя: `{user.display_name}`\n\n"
            
            f"**Исходные сервера:**\n"
            f"• Сервер #1 (1003525677640851496): {'✅ Есть роли' if role_check['has_first_server'] else '❌ Нет ролей'}\n"
        )
        
        if role_check['found_roles_first']:
            report += f"  Найденные роли: {', '.join(role_check['found_roles_first'])}\n"
        
        report += f"• Сервер #2 (1165977084099842098): {'✅ Есть роли' if role_check['has_second_server'] else '❌ Нет ролей'}\n"
        
        if role_check['found_roles_second']:
            report += f"  Найденные роли: {', '.join(role_check['found_roles_second'])}\n"
        
        report += f"\n**Целевой сервер (1457337712851026067):**\n"
        report += f"• Роль за сервер #1 ({TARGET_ROLE_ID}): {'✅ Есть' if has_target_role else '❌ Нет'}\n"
        report += f"• Роль за сервер #2 ({TARGET_ROLE_2_ID}): {'✅ Есть' if has_target_role_2 else '❌ Нет'}\n"
        
        report += f"\n**Статус:**\n"
        report += f"• Есть роли на любом сервере: {'✅ Да' if role_check['has_any_roles'] else '❌ Нет'}\n"
        report += f"• Статус бана: {'🔨 Забанен' if user.id in role_bot.banned_users else '✅ Не забанен'}\n"
        
        if user.id in role_bot.banned_users:
            ban_time = role_bot.banned_users[user.id]
            time_passed = datetime.now() - ban_time
            time_remaining = timedelta(minutes=10) - time_passed
            
            if time_remaining.total_seconds() > 0:
                minutes = int(time_remaining.total_seconds() // 60)
                seconds = int(time_remaining.total_seconds() % 60)
                report += f"• До разбана: {minutes}м {seconds}с\n"
        
        report += f"• Синхронизация: {'✅ Выполнена' if result else '❌ Не выполнена'}"
        
        await ctx.send(report)
        
    except Exception as e:
        await ctx.send(f"❌ Ошибка при проверке пользователя: {e}")
        print(f"❌ Ошибка в команде check_user: {e}")

@bot.command(name='check_all')
@commands.has_permissions(administrator=True)
async def check_all_command(ctx):
    """Проверить всех пользователей на сервере"""
    await ctx.send("🔄 Начинаю проверку всех пользователей на сервере...")
    
    try:
        target_server = bot.get_guild(TARGET_SERVER_ID)
        if not target_server:
            await ctx.send("❌ Целевой сервер не доступен")
            return
        
        members = [member for member in target_server.members if not member.bot]
        total_count = len(members)
        
        status_msg = await ctx.send(f"🔍 Найдено {total_count} пользователей для проверки...")
        
        processed = 0
        actions = 0
        banned_in_session = 0
        
        for member in members:
            processed += 1
            result = await role_bot.check_and_sync_user(member.id, check_ban=True)
            if result:
                actions += 1
            
            # Считаем новые баны в этой сессии
            if member.id in role_bot.banned_users:
                # Проверяем, был ли пользователь забанен недавно (в течение последней минуты)
                ban_time = role_bot.banned_users[member.id]
                if datetime.now() - ban_time < timedelta(minutes=1):
                    banned_in_session += 1
            
            # Обновляем статус каждые 10 пользователей
            if processed % 10 == 0:
                await status_msg.edit(content=f"🔄 Проверено {processed}/{total_count} пользователей ({actions} действий, {banned_in_session} новых банов)")
            
            await asyncio.sleep(0.05)
        
        await status_msg.edit(
            content=f"✅ **Проверка завершена!**\n"
                   f"• Проверено: {processed} пользователей\n"
                   f"• Выполнено действий: {actions}\n"
                   f"• Новых банов в сессии: {banned_in_session}\n"
                   f"• Всего забанено: {len(role_bot.banned_users)}"
        )
        
        # Отправляем полный лог в канал логов
        log_msg = (
            f"📊 **Ручная проверка всех пользователей**\n"
            f"• Инициировал: {ctx.author.mention}\n"
            f"• Проверено: {processed} пользователей\n"
            f"• Выполнено действий: {actions}\n"
            f"• Новых банов: {banned_in_session}\n"
            f"• Всего забанено: {len(role_bot.banned_users)}\n"
            f"• Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
        )
        await role_bot.log_to_channel(log_msg, color=0x0099ff)
        
    except Exception as e:
        await ctx.send(f"❌ Ошибка при проверке пользователей: {e}")
        print(f"❌ Ошибка в команде check_all: {e}")

@bot.command(name='check_bans')
@commands.has_permissions(administrator=True)
async def check_bans(ctx):
    """Показать список забаненных пользователей и время до разбана"""
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
                    # Должны быть разбанены в следующей проверке
                    ban_list.append(f"• {user.display_name} - ожидает разбана")
                    
            except Exception:
                ban_list.append(f"• ID {user_id} - пользователь не найден")
        
        if ban_list:
            await ctx.send(f"🔨 **Забаненные пользователи ({len(ban_list)}):**\n" + "\n".join(ban_list[:15]))
        else:
            await ctx.send("✅ Нет забаненных пользователей")
            
    except Exception as e:
        await ctx.send(f"❌ Ошибка при получении списка банов: {e}")

@bot.command(name='stats')
@commands.has_permissions(administrator=True)
async def stats_command(ctx):
    """Показать статистику бота"""
    target_server = bot.get_guild(TARGET_SERVER_ID)
    
    if not target_server:
        await ctx.send("❌ Целевой сервер не доступен")
        return
    
    total_members = len([m for m in target_server.members if not m.bot])
    banned_count = len(role_bot.banned_users)
    
    # Подсчитываем пользователей с ролями
    target_role = target_server.get_role(TARGET_ROLE_ID)
    target_role_2 = target_server.get_role(TARGET_ROLE_2_ID)
    
    with_role_1 = len([m for m in target_server.members if target_role in m.roles]) if target_role else 0
    with_role_2 = len([m for m in target_server.members if target_role_2 in m.roles]) if target_role_2 else 0
    
    stats_msg = (
        f"📊 **Статистика Role Sync Bot**\n"
        f"• Время работы: {datetime.now() - role_bot.start_time}\n"
        f"• Всего пользователей на целевом сервере: {total_members}\n"
        f"• С ролью за сервер #1 (1457339761395105833): {with_role_1}\n"
        f"• С ролью за сервер #2 (1457339829607071874): {with_role_2}\n"
        f"• Забанено: {banned_count} пользователей\n"
        f"• Авторазбан: через 10 минут\n"
        f"• Интервал проверки: 10 секунд\n"
        f"• Мониторинг активен: {'✅' if role_bot.is_monitoring else '❌'}\n\n"
        f"**Конфигурация:**\n"
        f"• Сервер #1: проверяет {len(SOURCE_ROLE_IDS)} ролей\n"
        f"• Сервер #2: проверяет {len(SOURCE_2_ROLE_IDS)} ролей"
    )
    
    await ctx.send(stats_msg)

@bot.command(name='sync_now')
@commands.has_permissions(administrator=True)
async def sync_now_command(ctx):
    """Немедленная синхронизация всех пользователей"""
    await ctx.send("⚡ Запускаю немедленную синхронизацию всех пользователей...")
    
    try:
        target_server = bot.get_guild(TARGET_SERVER_ID)
        if not target_server:
            await ctx.send("❌ Целевой сервер не доступен")
            return
        
        members = [member for member in target_server.members if not member.bot]
        total_count = len(members)
        
        status_msg = await ctx.send(f"🔍 Начинаю синхронизацию {total_count} пользователей...")
        
        processed = 0
        actions = 0
        
        for member in members:
            processed += 1
            result = await role_bot.check_and_sync_user(member.id, check_ban=True)
            if result:
                actions += 1
            
            # Обновляем статус каждые 5 пользователей (для быстрой обратной связи)
            if processed % 5 == 0:
                await status_msg.edit(content=f"⚡ Синхронизировано {processed}/{total_count} пользователей ({actions} действий)")
            
            await asyncio.sleep(0.01)  # Минимальная задержка для быстрой обработки
        
        await status_msg.edit(
            content=f"✅ **Синхронизация завершена!**\n"
                   f"• Обработано: {processed} пользователей\n"
                   f"• Выполнено действий: {actions}\n"
                   f"• Время: {datetime.now().strftime('%H:%M:%S')}"
        )
        
    except Exception as e:
        await ctx.send(f"❌ Ошибка при синхронизации: {e}")
        print(f"❌ Ошибка в команде sync_now: {e}")

# Запуск бота
def main():
    print("🚀 Запуск Role Sync Bot на Railway...")
    print("=" * 50)
    print(f"🎯 Целевой сервер: {TARGET_SERVER_ID}")
    print(f"🔍 Сервер #1: {SOURCE_SERVER_ID}")
    print(f"🔍 Сервер #2: {SOURCE_SERVER_2_ID}")
    print("=" * 50)
    
    # Получаем токен из переменных окружения Railway
    token = os.getenv('DISCORD_TOKEN')
    
    if not token:
        print("❌ Ошибка: DISCORD_TOKEN не найден")
        print("💡 Установите переменную в настройках Railway")
        return
    
    # Убираем бесконечный цикл перезапуска - Railway сам управляет перезапусками
    try:
        bot.run(token)
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()