import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, timedelta
import traceback
import os
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# НАСТРОЙКИ
# =========================================================

# Основной (целевой) сервер — тут выдаются/снимаются "суммирующие" роли и происходит бан
MAIN_SERVER_ID = 1536815201905541293

# ⚠️ ВПИШИТЕ АКТУАЛЬНЫЙ КАНАЛ ЛОГОВ НА ОСНОВНОМ СЕРВЕРЕ
LOG_CHANNEL_ID = 1536851779096944700  # placeholder — замените на реальный ID канала

# Длительность автобана при рассинхроне (роль есть, а исходной роли нет)
BAN_DURATION = timedelta(minutes=10)

# Интервал подстраховочной проверки (секунды). Основная реакция — мгновенная, по событию.
FALLBACK_SYNC_INTERVAL = 2

# ---------------------------------------------------------
# Маппинги: одна "целевая роль" на MAIN_SERVER_ID <- любая из ролей
# на конкретном сервере-источнике (OR-логика внутри группы)
# ---------------------------------------------------------
ROLE_MAPPINGS = [
    {
        "name": "Группа 1",
        "source_server_id": 1379837805366087710,
        "source_role_ids": [
            1396136669534621696,
            1381557998274478131,
            1379880312271671336,
            1379880183372447785,
            1379906654220456078,
            1471567668711653459,
            1379907394229899506,
        ],
        "target_role_id": 1536868470447284234,
    },
    {
        "name": "Группа 2",
        "source_server_id": 1003525677640851496,
        "source_role_ids": [
            1481402373879365835,
        ],
        "target_role_id": 1536868334346313848,
    },
    {
        "name": "Группа 3",
        "source_server_id": 1269934482044096533,
        "source_role_ids": [
            1269941326510690347,
            1269941327374585880,
            1269960238002602065,
            1350892590064603256,
            1269941342667280465,
        ],
        "target_role_id": 1536869777774219401,
    },
    {
        "name": "Группа 4",
        "source_server_id": 848325149191307264,
        "source_role_ids": [
            1277918655639846912,
        ],
        "target_role_id": 1536868392974422036,
    },
]

# Множество ID серверов-источников (для быстрой проверки в on_member_update)
SOURCE_SERVER_IDS = {m["source_server_id"] for m in ROLE_MAPPINGS}

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
            main_server = bot.get_guild(MAIN_SERVER_ID)
            user = await bot.fetch_user(self.user_id)

            await main_server.unban(user, reason="Разблокировка через кнопку")

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
            await interaction.response.send_message(f"❌ Ошибка при разблокировке: {e}", ephemeral=True)


class RoleSyncBot:
    def __init__(self):
        self.is_monitoring = False
        self.start_time = datetime.now()
        self.banned_users = {}  # {user_id: ban_time}

    # -----------------------------------------------------
    # Логи / баны
    # -----------------------------------------------------
    async def log_to_channel(self, message, color=0x00ff00, view=None):
        try:
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                embed = discord.Embed(description=message, color=color, timestamp=datetime.now())
                await channel.send(embed=embed, view=view)
            else:
                print(f"Не удалось найти канал логов: {LOG_CHANNEL_ID}")
        except Exception as e:
            print(f"Ошибка при отправке лога: {e}")

    async def ban_user(self, user_id, username, mapping_name, reason):
        try:
            main_server = bot.get_guild(MAIN_SERVER_ID)
            user = await bot.fetch_user(user_id)

            ban_reason = f"{reason} | Автобан до {(datetime.now() + BAN_DURATION).strftime('%d.%m.%Y %H:%M')}"
            await main_server.ban(user, reason=ban_reason, delete_message_days=0)

            ban_embed = discord.Embed(
                description=(
                    f"🔨 **Пользователь заблокирован**\n"
                    f"• Имя: `{username}`\n"
                    f"• Упоминание: <@{user_id}>\n"
                    f"• Профиль: [Перейти](https://discord.com/users/{user_id})\n\n"
                    f"**Причина:**\n"
                    f"• {reason} ({mapping_name})\n\n"
                    f"**Статус:**\n"
                    f"• Бан на 10 минут\n"
                    f"• Авторазбан: {(datetime.now() + BAN_DURATION).strftime('%d.%m.%Y %H:%M')}"
                ),
                color=0xff0000,
                timestamp=datetime.now()
            )

            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                await channel.send(embed=ban_embed, view=UnbanButton(user_id))

            self.banned_users[user_id] = datetime.now()
            print(f"🔨 Забанен пользователь {username} ({user_id}) — {mapping_name}")
            return True

        except discord.Forbidden:
            await self.log_to_channel(f"❌ Нет прав для бана пользователя `{username}`", color=0xff0000)
        except discord.NotFound:
            await self.log_to_channel(f"❌ Пользователь `{username}` не найден", color=0xff0000)
        except Exception as e:
            await self.log_to_channel(f"❌ Ошибка при бане пользователя `{username}`: {e}", color=0xff0000)

        return False

    async def auto_unban_users(self):
        try:
            main_server = bot.get_guild(MAIN_SERVER_ID)
            if not main_server:
                return

            current_time = datetime.now()
            users_to_unban = [
                uid for uid, ban_time in self.banned_users.items()
                if (current_time - ban_time) >= BAN_DURATION
            ]

            for user_id in users_to_unban:
                try:
                    user = await bot.fetch_user(user_id)
                    await main_server.unban(user, reason="Автоматический разбан после 10 минут")
                    del self.banned_users[user_id]

                    await self.log_to_channel(
                        f"🔓 **Автоматический разбан**\n"
                        f"• Пользователь: `{user.display_name}`\n"
                        f"• ID: `{user_id}`\n"
                        f"• Время разбана: {current_time.strftime('%d.%m.%Y %H:%M:%S')}",
                        color=0x00ff00
                    )
                    print(f"🔓 Автоматически разбанен {user.display_name} ({user_id})")

                except discord.NotFound:
                    del self.banned_users[user_id]
                except Exception as e:
                    print(f"❌ Ошибка при авторазбане {user_id}: {e}")

        except Exception as e:
            print(f"❌ Ошибка в авторазбане: {e}")

    # -----------------------------------------------------
    # Проверка ролей / синхронизация
    # -----------------------------------------------------
    def has_source_role(self, user_id, mapping):
        """Проверка по кэшу — без запросов к API, чтобы можно было гонять часто/мгновенно"""
        source_guild = bot.get_guild(mapping["source_server_id"])
        if not source_guild:
            return False, []
        member = source_guild.get_member(user_id)
        if not member:
            return False, []
        found = [r.name for r in member.roles if r.id in mapping["source_role_ids"]]
        return len(found) > 0, found

    async def sync_member_mapping(self, member: discord.Member, mapping):
        """Синхронизация одного пользователя по одной группе ролей. Возвращает описание действия или None."""
        target_role = member.guild.get_role(mapping["target_role_id"])
        if not target_role:
            return None

        has_source, found_roles = self.has_source_role(member.id, mapping)
        has_target = target_role in member.roles

        if has_source and not has_target:
            try:
                await member.add_roles(target_role, reason=f"Синхронизация — {mapping['name']}")
                msg = f"✅ Выдана роль «{target_role.name}» ({mapping['name']}) пользователю {member.display_name}"
                print(msg)
                await self.log_to_channel(
                    f"🔧 **Синхронизация ролей**\n"
                    f"• Пользователь: `{member.display_name}` (`{member.id}`)\n"
                    f"• Группа: {mapping['name']}\n"
                    f"• Действие: ✅ выдана роль «{target_role.name}»\n"
                    f"• Найденные роли-источники: {', '.join(found_roles)}",
                    color=0x0099ff
                )
                return msg
            except Exception as e:
                print(f"❌ Ошибка при выдаче роли ({mapping['name']}): {e}")
                return None

        elif not has_source and has_target:
            try:
                await member.remove_roles(target_role, reason=f"Синхронизация — нет ролей-источников ({mapping['name']})")
                print(f"🗑️ Снята роль «{target_role.name}» ({mapping['name']}) у {member.display_name}")

                await self.log_to_channel(
                    f"🔧 **Синхронизация ролей**\n"
                    f"• Пользователь: `{member.display_name}` (`{member.id}`)\n"
                    f"• Группа: {mapping['name']}\n"
                    f"• Действие: 🗑️ снята роль «{target_role.name}» (нет ролей-источников)",
                    color=0xff6600
                )

                # Рассинхрон: роль была без основания -> бан
                if member.id not in self.banned_users:
                    await self.ban_user(
                        member.id, member.display_name, mapping["name"],
                        reason="Наличие роли без соответствующих ролей-источников"
                    )
                return f"🗑️ Снята роль «{target_role.name}» ({mapping['name']}) + бан"
            except Exception as e:
                print(f"❌ Ошибка при снятии роли ({mapping['name']}): {e}")
                return None

        return None

    async def sync_member_all(self, member: discord.Member):
        """Прогоняет пользователя по всем группам маппинга"""
        actions = []
        for mapping in ROLE_MAPPINGS:
            result = await self.sync_member_mapping(member, mapping)
            if result:
                actions.append(result)
        return actions


role_bot = RoleSyncBot()


# =========================================================
# СОБЫТИЯ
# =========================================================

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user.name} успешно запущен!')
    print(f'📊 ID бота: {bot.user.id}')
    print(f'🕒 Время запуска: {datetime.now()}')

    main_server = bot.get_guild(MAIN_SERVER_ID)
    print(f'🔍 Основной сервер ({MAIN_SERVER_ID}): {"✅" if main_server else "❌"}')

    lines = []
    for mapping in ROLE_MAPPINGS:
        src = bot.get_guild(mapping["source_server_id"])
        status = "✅" if src else "❌"
        lines.append(f"   {mapping['name']}: сервер-источник {status} `{mapping['source_server_id']}` "
                      f"({len(mapping['source_role_ids'])} ролей) → роль `{mapping['target_role_id']}`")
    print("🔍 Маппинги ролей:")
    print("\n".join(lines))

    activity = discord.Activity(type=discord.ActivityType.watching, name=f"{len(ROLE_MAPPINGS)} групп ролей")
    await bot.change_presence(activity=activity)

    await load_banned_users()

    startup_msg = (
        f"🟢 **Role Sync Bot запущен**\n"
        f"• Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"• Основной сервер: {'✅' if main_server else '❌'} `{MAIN_SERVER_ID}`\n\n"
        f"**Маппинги:**\n" + "\n".join(
            f"• {m['name']}: `{m['source_server_id']}` ({len(m['source_role_ids'])} роль(ей)) → `{m['target_role_id']}`"
            for m in ROLE_MAPPINGS
        ) + "\n\n"
        f"**Настройки:**\n"
        f"• Реакция: мгновенно по событию + подстраховка каждые {FALLBACK_SYNC_INTERVAL} сек\n"
        f"• Авторазбан: 10 минут"
    )
    await role_bot.log_to_channel(startup_msg, color=0x00ff00)

    role_bot.is_monitoring = True
    fallback_sync_task.start()
    auto_unban_task.start()

    await bot.wait_until_ready()
    await asyncio.sleep(10)
    await sync_all_members_once()


async def load_banned_users():
    try:
        main_server = bot.get_guild(MAIN_SERVER_ID)
        if main_server:
            bans = [entry async for entry in main_server.bans()]
            for ban_entry in bans:
                role_bot.banned_users[ban_entry.user.id] = datetime.now() - timedelta(minutes=5)
            print(f"📋 Загружено {len(bans)} забаненных пользователей")
    except Exception as e:
        print(f"❌ Ошибка при загрузке банов: {e}")


async def sync_all_members_once():
    """Полная проверка всех пользователей при старте (с прогрессом в лог-канале)"""
    try:
        main_server = bot.get_guild(MAIN_SERVER_ID)
        if not main_server:
            print("❌ Основной сервер недоступен")
            return

        members = [m for m in main_server.members if not m.bot]
        total = len(members)
        print(f"🔍 Начинаю проверку всех {total} пользователей...")

        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        progress_msg = await log_channel.send(f"🔄 **Начинаю проверку {total} пользователей...**") if log_channel else None

        processed, actions_count = 0, 0
        for member in members:
            processed += 1
            actions = await role_bot.sync_member_all(member)
            actions_count += len(actions)

            if progress_msg and processed % 20 == 0:
                try:
                    await progress_msg.edit(content=f"🔄 Проверено {processed}/{total} • действий: {actions_count}")
                except Exception:
                    pass

        if progress_msg:
            await progress_msg.edit(content=f"✅ **Проверка завершена!** {processed}/{total} • действий: {actions_count}")

        print(f"✅ Проверено {processed} пользователей, действий: {actions_count}")

    except Exception as e:
        print(f"❌ Ошибка при полной проверке: {e}")
        traceback.print_exc()


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Мгновенная реакция на изменение ролей на серверах-источниках"""
    try:
        if before.guild.id not in SOURCE_SERVER_IDS:
            return
        if before.roles == after.roles:
            return

        main_server = bot.get_guild(MAIN_SERVER_ID)
        if not main_server:
            return

        main_member = main_server.get_member(after.id)
        if not main_member or main_member.bot:
            return

        # Синкаем только те группы, что относятся к этому серверу-источнику
        relevant = [m for m in ROLE_MAPPINGS if m["source_server_id"] == before.guild.id]
        for mapping in relevant:
            await role_bot.sync_member_mapping(main_member, mapping)

    except Exception as e:
        print(f"❌ Ошибка в on_member_update: {e}")


@tasks.loop(seconds=FALLBACK_SYNC_INTERVAL)
async def fallback_sync_task():
    """Лёгкая подстраховка — проверка по кэшу (без лишних API-запросов), на случай пропущенных событий"""
    try:
        main_server = bot.get_guild(MAIN_SERVER_ID)
        if not main_server:
            return
        for member in main_server.members:
            if member.bot:
                continue
            await role_bot.sync_member_all(member)
    except Exception as e:
        print(f"❌ Ошибка в подстраховочной синхронизации: {e}")


@tasks.loop(minutes=1)
async def auto_unban_task():
    try:
        await role_bot.auto_unban_users()
    except Exception as e:
        print(f"❌ Ошибка в авторазбане: {e}")


# =========================================================
# КОМАНДЫ
# =========================================================

@bot.command(name='check_user')
@commands.has_permissions(administrator=True)
async def check_user_command(ctx, user: discord.Member = None):
    if not user:
        user = ctx.author

    await ctx.send(f"🔍 Проверяю пользователя {user.mention}...")

    try:
        report = f"📋 **Отчёт по пользователю {user.mention}**\n• ID: `{user.id}`\n• Имя: `{user.display_name}`\n\n"

        for mapping in ROLE_MAPPINGS:
            has_source, found = role_bot.has_source_role(user.id, mapping)
            target_role = ctx.guild.get_role(mapping["target_role_id"])
            has_target = target_role in user.roles if target_role else False

            report += (
                f"**{mapping['name']}** (источник `{mapping['source_server_id']}`)\n"
                f"• Исходные роли: {'✅ ' + ', '.join(found) if has_source else '❌ Нет'}\n"
                f"• Целевая роль «{target_role.name if target_role else '???'}»: {'✅ Есть' if has_target else '❌ Нет'}\n\n"
            )

        report += f"**Статус бана:** {'🔨 Забанен' if user.id in role_bot.banned_users else '✅ Не забанен'}"

        if user.id in role_bot.banned_users:
            time_remaining = BAN_DURATION - (datetime.now() - role_bot.banned_users[user.id])
            if time_remaining.total_seconds() > 0:
                m, s = divmod(int(time_remaining.total_seconds()), 60)
                report += f"\n• До разбана: {m}м {s}с"

        actions = await role_bot.sync_member_all(user)
        report += f"\n\n**Синхронизация:** {'выполнены действия: ' + '; '.join(actions) if actions else 'изменений не требуется'}"

        await ctx.send(report)

    except Exception as e:
        await ctx.send(f"❌ Ошибка при проверке пользователя: {e}")
        print(f"❌ Ошибка в check_user: {e}")


@bot.command(name='check_all')
@commands.has_permissions(administrator=True)
async def check_all_command(ctx):
    await ctx.send("🔄 Начинаю проверку всех пользователей...")
    try:
        members = [m for m in ctx.guild.members if not m.bot]
        total = len(members)
        status_msg = await ctx.send(f"🔍 Найдено {total} пользователей...")

        processed, actions_count = 0, 0
        for member in members:
            processed += 1
            actions = await role_bot.sync_member_all(member)
            actions_count += len(actions)

            if processed % 20 == 0:
                await status_msg.edit(content=f"🔄 Проверено {processed}/{total} • действий: {actions_count}")

        await status_msg.edit(content=f"✅ **Готово!** Проверено: {processed} • действий: {actions_count} • забанено всего: {len(role_bot.banned_users)}")

        await role_bot.log_to_channel(
            f"📊 **Ручная проверка всех пользователей**\n"
            f"• Инициировал: {ctx.author.mention}\n"
            f"• Проверено: {processed}\n"
            f"• Действий: {actions_count}\n"
            f"• Забанено всего: {len(role_bot.banned_users)}",
            color=0x0099ff
        )

    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")
        print(f"❌ Ошибка в check_all: {e}")


@bot.command(name='check_bans')
@commands.has_permissions(administrator=True)
async def check_bans(ctx):
    try:
        current_time = datetime.now()
        ban_list = []
        for user_id, ban_time in role_bot.banned_users.items():
            try:
                user = await bot.fetch_user(user_id)
                remaining = BAN_DURATION - (current_time - ban_time)
                if remaining.total_seconds() > 0:
                    m, s = divmod(int(remaining.total_seconds()), 60)
                    ban_list.append(f"• {user.display_name} — {m}м {s}с")
                else:
                    ban_list.append(f"• {user.display_name} — ожидает разбана")
            except Exception:
                ban_list.append(f"• ID {user_id} — не найден")

        if ban_list:
            await ctx.send(f"🔨 **Забаненные ({len(ban_list)}):**\n" + "\n".join(ban_list[:15]))
        else:
            await ctx.send("✅ Нет забаненных пользователей")

    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")


@bot.command(name='stats')
@commands.has_permissions(administrator=True)
async def stats_command(ctx):
    main_server = bot.get_guild(MAIN_SERVER_ID)
    if not main_server:
        await ctx.send("❌ Основной сервер недоступен")
        return

    total_members = len([m for m in main_server.members if not m.bot])

    lines = [f"📊 **Статистика Role Sync Bot**",
             f"• Время работы: {datetime.now() - role_bot.start_time}",
             f"• Всего пользователей: {total_members}",
             f"• Забанено сейчас: {len(role_bot.banned_users)}",
             f"• Реакция: событие + подстраховка {FALLBACK_SYNC_INTERVAL} сек",
             f"• Мониторинг: {'✅' if role_bot.is_monitoring else '❌'}",
             "", "**По группам:**"]

    for mapping in ROLE_MAPPINGS:
        target_role = main_server.get_role(mapping["target_role_id"])
        count = len([m for m in main_server.members if target_role in m.roles]) if target_role else 0
        lines.append(f"• {mapping['name']}: {count} чел. с ролью «{target_role.name if target_role else '???'}»")

    await ctx.send("\n".join(lines))


@bot.command(name='sync_now')
@commands.has_permissions(administrator=True)
async def sync_now_command(ctx):
    await ctx.send("⚡ Немедленная синхронизация всех пользователей...")
    try:
        members = [m for m in ctx.guild.members if not m.bot]
        total = len(members)
        status_msg = await ctx.send(f"🔍 Синхронизирую {total} пользователей...")

        processed, actions_count = 0, 0
        for member in members:
            processed += 1
            actions = await role_bot.sync_member_all(member)
            actions_count += len(actions)
            if processed % 10 == 0:
                await status_msg.edit(content=f"⚡ {processed}/{total} • действий: {actions_count}")

        await status_msg.edit(content=f"✅ **Готово!** {processed} пользователей • действий: {actions_count}")

    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")
        print(f"❌ Ошибка в sync_now: {e}")


# =========================================================
# ЗАПУСК
# =========================================================

def main():
    print("🚀 Запуск Role Sync Bot на Railway...")
    print("=" * 50)
    print(f"🎯 Основной сервер: {MAIN_SERVER_ID}")
    for m in ROLE_MAPPINGS:
        print(f"🔍 {m['name']}: {m['source_server_id']} → {m['target_role_id']}")
    print("=" * 50)

    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ Ошибка: DISCORD_TOKEN не найден")
        print("💡 Установите переменную в настройках Railway")
        return

    try:
        bot.run(token)
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()