import asyncio
import json
import os
from datetime import timedelta

from dotenv import load_dotenv
import discord
from discord.ext import commands

# Load variables from .env in this project and override any existing environment variables.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=True)

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token."
    )
ROLE_CONFIG_PATH = "roles.json"
REMINDER_CONFIG_PATH = "reminders.json"
PING_ROLE_ID = int(os.getenv("PING_ROLE_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
ADMIN_ROLE_NAME = "vse magushi"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
reminders_restored = False


def load_role_names() -> list[str]:
    try:
        with open(ROLE_CONFIG_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, list) and all(isinstance(name, str) for name in data):
            # Preserve order while removing duplicate role names.
            return list(dict.fromkeys(data))
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    return ["Gamer", "Artist", "Member"]


def load_reminders() -> list[dict[str, int]]:
    try:
        with open(REMINDER_CONFIG_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, list):
            valid_reminders = []
            for item in data:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("channel_id"), int)
                    and isinstance(item.get("role_id"), int)
                    and isinstance(item.get("target_time"), int)
                ):
                    valid_reminders.append(item)
            return valid_reminders
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    return []


def save_reminders(reminders: list[dict[str, int]]) -> None:
    try:
        with open(REMINDER_CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(reminders, file, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Failed to save reminders.json:", e)


def add_reminder(channel_id: int, role_id: int, target_time: int) -> None:
    reminders = load_reminders()
    reminder = {
        "channel_id": channel_id,
        "role_id": role_id,
        "target_time": target_time,
    }
    if reminder not in reminders:
        reminders.append(reminder)
        save_reminders(reminders)


def remove_reminder(channel_id: int, role_id: int, target_time: int) -> None:
    reminders = load_reminders()
    filtered = [
        r
        for r in reminders
        if not (
            r.get("channel_id") == channel_id
            and r.get("role_id") == role_id
            and r.get("target_time") == target_time
        )
    ]
    save_reminders(filtered)


def is_admin_member(member: discord.Member | discord.User) -> bool:
    if not isinstance(member, discord.Member):
        return False
    return any(role.name == ADMIN_ROLE_NAME for role in member.roles)


async def schedule_role_ping(channel: discord.TextChannel, role_id: int, target_time: int) -> None:
    reminder_time = target_time - 300  # 5 minutes before
    now_ts = int(discord.utils.utcnow().timestamp())

    if now_ts >= target_time:
        remove_reminder(channel.id, role_id, target_time)
        return

    if now_ts >= reminder_time:
        try:
            await channel.send(
                f"<@&{role_id}> Reminder: vibros at <t:{target_time}:t>."
            )
        except Exception as e:
            print("Failed to send vibros reminder:", e)
        finally:
            remove_reminder(channel.id, role_id, target_time)
        return

    delay = reminder_time - now_ts
    await asyncio.sleep(delay)
    try:
        await channel.send(
            f"<@&{role_id}> Reminder: vibros at <t:{target_time}:t>."
        )
    except Exception as e:
        print("Failed to send vibros reminder:", e)
    finally:
        remove_reminder(channel.id, role_id, target_time)


async def restore_reminders() -> None:
    reminders = load_reminders()
    if not reminders:
        return

    for reminder in reminders:
        channel_id = reminder["channel_id"]
        role_id = reminder["role_id"]
        target_time = reminder["target_time"]
        channel = bot.get_channel(channel_id)

        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception:
                continue

        if not isinstance(channel, discord.TextChannel):
            continue

        async def _schedule(channel_obj: discord.TextChannel, role_id: int, target_time: int) -> None:
            await schedule_role_ping(channel_obj, role_id, target_time)

        bot.loop.create_task(_schedule(channel, role_id, target_time))


def can_manage_role(role: discord.Role, bot_member: discord.Member | None) -> bool:
    if bot_member is None:
        return False
    if role.is_default() or role.managed:
        return False
    return role.position < bot_member.top_role.position


def get_manageable_role_names(guild: discord.Guild) -> list[str]:
    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.manage_roles:
        return []

    return [
        r.name
        for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
        if can_manage_role(r, bot_member) and r.name != ADMIN_ROLE_NAME
    ]


class RoleButton(discord.ui.Button):
    def __init__(self, role_name: str, index: int):
        custom_id = f"role_btn:{index}:{role_name}"
        super().__init__(label=role_name, style=discord.ButtonStyle.primary, custom_id=custom_id)
        self.role_name = role_name

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Role buttons only work inside a server.", ephemeral=True
            )
            return

        role = discord.utils.get(guild.roles, name=self.role_name)
        if role is None:
            await interaction.response.send_message(
                f"Role {self.role_name!r} was not found on this server.", ephemeral=True
            )
            return

        member = interaction.user
        bot_member = guild.me

        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "I don't have permission to manage roles on this server.",
                ephemeral=True,
            )
            return

        if not can_manage_role(role, bot_member):
            await interaction.response.send_message(
                "I cannot manage that role because it is at or above my highest role.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Role button interaction")
                action = "Removed"
            else:
                await member.add_roles(role, reason="Role button interaction")
                action = "Added"

            await interaction.followup.send(
                f"{action} the role {role.name}.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to manage that role.", ephemeral=True
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "Failed to update your role. Please try again.", ephemeral=True
            )


class RoleMenuView(discord.ui.View):
    def __init__(self, role_names: list[str]):
        super().__init__(timeout=None)
        seen = set()
        for index, role_name in enumerate(role_names):
            if role_name in seen:
                continue
            seen.add(role_name)
            self.add_item(RoleButton(role_name, index))


@bot.event
async def on_ready():
    global reminders_restored
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    if not reminders_restored:
        reminders_restored = True
        await restore_reminders()

    # Extract roles from the configured guild (by ID) or fall back to the
    # first available guild. This keeps `roles.json` in sync with the server
    # the bot should use for role buttons.
    guild = None
    if GUILD_ID:
        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            print(f"Configured GUILD_ID={GUILD_ID} not found in bot's guild cache.")
    if guild is None and bot.guilds:
        guild = bot.guilds[0]
        print(f"No valid GUILD_ID configured; using first guild: {guild.name} ({guild.id})")

    if guild is not None:
        roles = list(dict.fromkeys(
            name
            for name in get_manageable_role_names(guild)
            if name != bot.user.name
        ))
        try:
            with open(ROLE_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(roles, f, ensure_ascii=False, indent=2)
            print(f"roles.json updated with {len(roles)} roles from guild {guild.name} ({guild.id})")
        except Exception as e:
            print("Failed to write roles.json:", e)

        # Register view for the freshly loaded roles so button interactions work
        # immediately. This also ensures next restart will read the updated file
        # via setup_hook.
        bot.add_view(RoleMenuView(roles))
        print("Persistent button views registered (from guild roles)!")
    else:
        print("No guilds available to extract roles from.")

    print("------")


async def setup_hook() -> None:
    roles_list = load_role_names()
    if bot.guilds:
        guild = bot.guilds[0]
        manageable_names = set(get_manageable_role_names(guild))
        roles_list = [name for name in roles_list if name in manageable_names]
    roles_list = list(dict.fromkeys(roles_list))

    bot.add_view(RoleMenuView(roles_list))
    print("Persistent button views registered!")


bot.setup_hook = setup_hook


@bot.command(name="vibros", aliases=["vib", "v", "emmision"])
async def vibros(
    ctx: commands.Context,
    percentage: str = None,
    channel: discord.TextChannel = None,
):
    """Calculate vibros time.

    Usage:
    - `!vibros` -> bot prompts for percentage interactively
    - `!vibros 57%` or `!vibros 57` -> direct input
    """

    def parse_percent(text: str) -> float | None:
        if text is None:
            return None
        t = text.strip().replace("%", "")
        try:
            return float(t)
        except ValueError:
            return None

    # If no percentage provided, prompt the user
    if percentage is None:
        await ctx.send("Enter percentage (e.g. 57%):")

        def check(m: discord.Message) -> bool:
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            reply: discord.Message = await bot.wait_for("message", timeout=20.0, check=check)
        except Exception:
            await ctx.send("Timed out waiting for a percentage.")
            return

        percentage = reply.content

    pct = parse_percent(percentage)
    if pct is None:
        await ctx.reply("Could not parse percentage. Use a number like `57` or `57%`.", mention_author=False)
        return

    if pct < 0 or pct > 100:
        await ctx.reply("Please provide a percentage between 0 and 100.", mention_author=False)
        return

    minutes_to_add = (pct - 50) * 72 / 60
    now_utc = discord.utils.utcnow()
    target_time = now_utc + timedelta(minutes=minutes_to_add)
    unix_timestamp = int(target_time.timestamp())

    response_lines = [
        "**Vibros EPTI**",
        f"Input Percentage: `{pct}%`",
        f"Vibros at: <t:{unix_timestamp}:t> (<t:{unix_timestamp}:R>)",
    ]
    if PING_ROLE_ID:
        response_lines.insert(0, f"<@&{PING_ROLE_ID}>")

    response_msg = "\n".join(response_lines)
    output_channel = channel or ctx.channel
    await output_channel.send(response_msg)

    if PING_ROLE_ID:
        add_reminder(output_channel.id, PING_ROLE_ID, unix_timestamp)
        bot.loop.create_task(schedule_role_ping(output_channel, PING_ROLE_ID, unix_timestamp))

    if output_channel != ctx.channel:
        await ctx.reply(
            f"I posted the calculated time in {output_channel.mention}.",
            mention_author=False,
        )


@bot.command(name="roles")
async def roles(ctx: commands.Context, channel: discord.TextChannel = None):
    if not is_admin_member(ctx.author):
        await ctx.reply(
            f"Only members with the {ADMIN_ROLE_NAME!r} role can use this command.",
            mention_author=False,
        )
        return

    role_names = [name for name in load_role_names() if name not in {bot.user.name, ADMIN_ROLE_NAME}]
    if ctx.guild is not None:
        manageable_names = set(get_manageable_role_names(ctx.guild))
        role_names = [name for name in role_names if name in manageable_names]
    role_names = list(dict.fromkeys(role_names))

    if not role_names:
        await ctx.reply(
            "No roles are configured. Please update roles.json with role names.",
            mention_author=False,
        )
        return

    output_channel = channel or ctx.channel
    view = RoleMenuView(role_names)
    await output_channel.send(
        "Press a button to add or remove the matching role.", view=view
    )

    if output_channel != ctx.channel:
        await ctx.reply(
            f"I posted the role button menu in {output_channel.mention}.",
            mention_author=False,
        )


@bot.command(name="reloadroles")
async def reload_roles(ctx: commands.Context):
    if not is_admin_member(ctx.author):
        await ctx.reply(
            f"Only members with the {ADMIN_ROLE_NAME!r} role can use this command.",
            mention_author=False,
        )
        return

    loaded = load_role_names()
    if loaded:
        await ctx.reply(
            f"Reloaded roles.json with {len(loaded)} role(s).",
            mention_author=False,
        )
    else:
        await ctx.reply(
            "Failed to reload roles.json. Please check the file format.",
            mention_author=False,
        )


if __name__ == "__main__":
    bot.run(TOKEN)
