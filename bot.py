import logging
import os
import re

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv(encoding='utf-8-sig')
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv('DISCORD_TOKEN', '').strip()


def read_id(name):
    value = os.getenv(name, '').strip()
    if not value.isdecimal() or int(value) <= 0:
        raise ValueError(f'Укажите правильный {name} в файле .env')
    return int(value)


class ApplicationModal(discord.ui.Modal, title='Заявка на вступление'):
    first_name = discord.ui.TextInput(label='Имя', max_length=80, placeholder='Серёжа')
    last_name = discord.ui.TextInput(label='Фамилия', max_length=80, placeholder='Дворников')
    age = discord.ui.TextInput(label='Возраст', max_length=3, placeholder='Например: 18')
    static_id = discord.ui.TextInput(label='Статический ID', max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.age.value.isdecimal() or not 1 <= int(self.age.value) <= 120:
            await interaction.response.send_message('Укажите возраст числом от 1 до 120 и отправьте заявку ещё раз.', ephemeral=True)
            return
        channel = interaction.guild.get_channel(read_id('APPLICATION_CHANNEL_ID')) if interaction.guild else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message('Канал заявок не найден. Сообщите администрации.', ephemeral=True)
            return
        embed = discord.Embed(title='Новая заявка на вступление', color=discord.Color.blue())
        for label, value in [('Имя', self.first_name.value), ('Фамилия', self.last_name.value), ('Возраст', self.age.value), ('Статический ID', self.static_id.value)]:
            embed.add_field(name=label, value=value, inline=False)
        embed.add_field(name='Заявитель', value=interaction.user.mention, inline=False)
        embed.set_footer(text=f'ID заявителя: {interaction.user.id}')
        try:
            await channel.send(embed=embed, view=ReviewView())
        except discord.Forbidden:
            await interaction.response.send_message('Не удалось отправить заявку. Сообщите администрации.', ephemeral=True)
            return
        await interaction.response.send_message('Заявка отправлена руководству.', ephemeral=True)


class ApplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Подать заявку', style=discord.ButtonStyle.primary, custom_id='application:open')
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApplicationModal())


class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def decide(self, interaction: discord.Interaction, accept: bool):
        if not isinstance(interaction.user, discord.Member) or not any(role.id == read_id('MANAGEMENT_ROLE_ID') for role in interaction.user.roles):
            await interaction.response.send_message('Эта кнопка доступна только руководству.', ephemeral=True)
            return
        if interaction.channel_id != read_id('APPLICATION_CHANNEL_ID') or not interaction.message.embeds:
            await interaction.response.send_message('Не удалось определить заявку.', ephemeral=True)
            return
        embed = interaction.message.embeds[0]
        if any(field.name == 'Решение' for field in embed.fields):
            await interaction.response.send_message('По этой заявке уже принято решение.', ephemeral=True)
            return
        match = re.fullmatch(r'ID заявителя: (\d+)', embed.footer.text or '')
        if not match or not interaction.guild:
            await interaction.response.send_message('Не удалось определить заявителя.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        nickname_warning = None
        if accept:
            role = interaction.guild.get_role(1572358924454207528)
            if role is None:
                await interaction.followup.send('Роль для принятого участника не найдена на сервере.', ephemeral=True)
                return
            try:
                member = await interaction.guild.fetch_member(int(match.group(1)))
                await member.add_roles(role, reason=f'Заявка принята: {interaction.user}')
            except discord.NotFound:
                await interaction.followup.send('Заявитель больше не состоит на сервере.', ephemeral=True)
                return
            except discord.Forbidden:
                await interaction.followup.send('Не удалось выдать роль. Проверьте право бота «Управлять ролями» и расположение его роли выше выдаваемой.', ephemeral=True)
                return
            except discord.HTTPException:
                await interaction.followup.send('Discord не смог выдать роль. Попробуйте ещё раз.', ephemeral=True)
                return
            fields = {field.name: field.value for field in embed.fields}
            nickname = f"{fields.get('Имя', '')} {fields.get('Фамилия', '')} | {fields.get('Статический ID', '')}"
            if not all(fields.get(name) for name in ('Имя', 'Фамилия', 'Статический ID')) or len(nickname) > 32:
                nickname_warning = 'Не удалось изменить имя: данные отсутствуют или имя длиннее 32 символов.'
            else:
                try:
                    await member.edit(nick=nickname, reason=f'Заявка принята: {interaction.user}')
                except (discord.Forbidden, discord.HTTPException):
                    nickname_warning = 'Не удалось изменить имя. Проверьте право бота «Управлять никнеймами» и иерархию ролей.'
        embed.add_field(name='Решение', value=f'{"Принят(а)" if accept else "Отказано"} — {interaction.user.mention}', inline=False)
        embed.color = discord.Color.green() if accept else discord.Color.red()
        await interaction.message.edit(embed=embed, view=self)
        result = 'Заявка принята, роль выдана.' if accept else 'В заявке отмечен отказ.'
        if nickname_warning:
            result += ' ' + nickname_warning
        await interaction.followup.send(result, ephemeral=True)

    @discord.ui.button(label='Принять', style=discord.ButtonStyle.success, custom_id='application:accept')
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.decide(interaction, True)

    @discord.ui.button(label='Отказать', style=discord.ButtonStyle.danger, custom_id='application:reject')
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.decide(interaction, False)

    @discord.ui.button(label='Вызвать на обзвон', style=discord.ButtonStyle.success, custom_id='application:call')
    async def call(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id = read_id('MANAGEMENT_ROLE_ID')
        if not isinstance(interaction.user, discord.Member) or not any(role.id == role_id for role in interaction.user.roles):
            await interaction.response.send_message('Эта кнопка доступна только руководству.', ephemeral=True)
            return
        if interaction.channel_id != read_id('APPLICATION_CHANNEL_ID') or not interaction.message.embeds:
            await interaction.response.send_message('Не удалось определить заявку.', ephemeral=True)
            return
        footer = interaction.message.embeds[0].footer.text or ''
        match = re.fullmatch(r'ID заявителя: (\d+)', footer)
        if not match:
            await interaction.response.send_message('Не удалось определить заявителя.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            user = await interaction.client.fetch_user(int(match.group(1)))
            await user.send(
                f'Вас вызывают на обзвон по заявке на сервере «{interaction.guild.name}».\n'
                f'Канал для обзвона: https://discord.com/channels/{interaction.guild.id}/1572388238151127111\n'
                f'Для связи напишите руководителю, который вас вызвал: {interaction.user.mention}.'
            )
        except discord.Forbidden:
            await interaction.followup.send('Не удалось отправить личное сообщение: возможно, у пользователя закрыты личные сообщения. Свяжитесь с ним другим способом.', ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.followup.send('Discord не смог доставить уведомление. Попробуйте ещё раз.', ephemeral=True)
            return
        await interaction.followup.send('Уведомление об обзвоне отправлено в личные сообщения.', ephemeral=True)
        await interaction.channel.send(f'{interaction.user.mention} вызвал(а) {user.mention} на обзвон.', allowed_mentions=discord.AllowedMentions.none())


class ApplicationBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(ApplyView())
        self.add_view(ReviewView())
        guild = discord.Object(id=read_id('GUILD_ID'))
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)


bot = ApplicationBot(command_prefix='!', intents=discord.Intents.default())


@bot.event
async def on_ready():
    logging.info('Бот запущен: %s', bot.user)


@bot.tree.command(name='панель_заявок', description='Разместить кнопку для подачи заявки')
@app_commands.checks.has_permissions(manage_guild=True)
async def application_panel(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id != read_id('GUILD_ID'):
        await interaction.response.send_message('Команда доступна только на настроенном сервере.', ephemeral=True)
        return
    await interaction.response.send_message('Панель опубликована.', ephemeral=True)
    await interaction.channel.send('Нажмите кнопку ниже, чтобы подать заявку на вступление.', view=ApplyView())


if __name__ == '__main__':
    if not TOKEN:
        raise SystemExit('Укажите DISCORD_TOKEN в файле .env')
    for setting in ('GUILD_ID', 'APPLICATION_CHANNEL_ID', 'MANAGEMENT_ROLE_ID'):
        read_id(setting)
    bot.run(TOKEN)

