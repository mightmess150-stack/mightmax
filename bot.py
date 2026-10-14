import discord
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
import asyncio
import random
from datetime import datetime, timedelta
import re
import aiosqlite
from openai import OpenAI

# ----------------- إعدادات البوت والـ Intents -----------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------- متغيرات وتعارضات الإعدادات (عدلها حسب سيرفرك) -----------------
WELCOME_CHANNEL_ID = 123456789012345678  # آيدي روم الترحيب
AUTO_ROLE_ID = 123456789012345678       # آيدي الرتبة التلقائية
SUPPORT_ROLE_ID = 123456789012345678    # آيدي رتبة الدعم الفني
TICKET_CATEGORY_ID = 123456789012345678 # آيدي قسم التكتات
AI_CHANNEL_ID = 123456789012345678      # آيدي روم الذكاء الاصطناعي

# تهيئة OpenAI (استبدل المفتاح بمفتاحك أو ضعه في ملف بيئة .env)
client_ai = OpenAI(api_key="YOUR_OPENAI_API_KEY")

# نظام XP المؤقت (يفضل استبداله بقاعدة بيانات لاحقاً)
user_data = {}

# تهيئة قاعدة بيانات الاقتصاد عند تشغيل البوت
async def init_db():
    async with aiosqlite.connect("economy.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                bank INTEGER DEFAULT 0,
                last_daily REAL DEFAULT 0
            )
        """)
        await db.commit()

@bot.event
async def on_ready():
    await init_db()
    try:
        synced = await bot.tree.sync()
        print(f"تم مزامنة {len(synced)} أامر بنجاح. البوت يعمل الآن باسم: {bot.user}")
    except Exception as e:
        print(f"خطأ في المزامنة: {e}")

# ----------------- 1. نظام الترحيب ورتبة البداية -----------------
@bot.event
async def on_member_join(member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if not channel:
        return
    
    try:
        avatar_url = member.display_avatar.url
        response = requests.get(avatar_url)
        avatar = Image.open(BytesIO(response.content)).resize((160, 160))
        
        background = Image.new('RGB', (800, 300), '#1a1d2e')
        draw = ImageDraw.Draw(background)
        draw.rectangle([0, 0, 800, 8], fill='#5865F2')
        
        mask = Image.new('L', (160, 160), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, 160, 160), fill=255)
        background.paste(avatar, (70, 70), mask)
        
        background.save('welcome.png')
        
        embed = discord.Embed(
            description=f"مرحباً {member.mention} في **{member.guild.name}** ✨",
            color=0x5865F2
        )
        embed.set_image(url="attachment://welcome.png")
        
        await channel.send(embed=embed, file=discord.File('welcome.png'))
    except Exception as e:
        print(f"خطأ في صورة الترحيب: {e}")
    
    role = member.guild.get_role(AUTO_ROLE_ID)
    if role:
        try:
            await member.add_roles(role)
        except Exception as e:
            print(f"خطأ في إعطاء الرتبة: {e}")

# ----------------- 2. نظام التكتات (Tickets) -----------------
class TicketCloseView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="إغلاق التكت", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket_btn")
    async def close_callback(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("🔒 سيتم إغلاق التكت خلال 5 ثوانٍ...")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except:
            pass

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="فتح تكت", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="create_ticket_btn")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        support_role = guild.get_role(SUPPORT_ROLE_ID)
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        
        category = discord.utils.get(guild.categories, id=TICKET_CATEGORY_ID)
        
        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            overwrites=overwrites,
            category=category
        )
        
        embed = discord.Embed(title="🎫 تكت جديد", description=f"أهلاً بك {interaction.user.mention}\nيرجى توضيح مشكلتك وسيقوم الدعم بالرد عليك قريباً.", color=0x5865F2)
        await channel.send(content=f"{interaction.user.mention} {support_role.mention if support_role else ''}", embed=embed, view=TicketCloseView())
        await interaction.response.send_message(f"✅ تم إنشاء تكت الخاص بك: {channel.mention}", ephemeral=True)

@bot.tree.command(name="setup_tickets", description="إرسال رسالة إنشاء التكتات")
@app_commands.checks.has_permissions(administrator=True)
async def setup_tickets(interaction: discord.Interaction):
    embed = discord.Embed(title="الدعم الفني", description="اضغط على الزر أدناه لفتح تكت جديد والمساعدة.", color=0x5865F2)
    await interaction.channel.send(embed=embed, view=TicketView())
    await interaction.response.send_message("✅ تم إرسال لوحة التكتات بنجاح", ephemeral=True)

# ----------------- 3. دمج أحداث الرسائل (XP + الذكاء الاصطناعي في روم مخصص) -----------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # --- نظام XP ---
    if message.guild:
        key = f"{message.guild.id}_{message.author.id}"
        if key not in user_data:
            user_data[key] = {"xp": 0, "level": 0}
        
        user_data[key]["xp"] += random.randint(15, 25)
        needed = user_data[key]["level"] * 300 + 100
        
        if user_data[key]["xp"] >= needed:
            user_data[key]["level"] += 1
            user_data[key]["xp"] = 0
            
            embed = discord.Embed(
                title="🎉 ليفل أب!",
                description=f"مبارك {message.author.mention}, لقد وصلت للمستوى **{user_data[key]['level']}**!",
                color=0x5865F2
            )
            try:
                await message.channel.send(embed=embed)
            except:
                pass

    # --- نظام ردود الذكاء الاصطناعي التلقائية في الروم المخصص ---
    if message.channel.id == AI_CHANNEL_ID and not message.content.startswith("!"):
        async with message.channel.typing():
            try:
                completion = client_ai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "أنت مساعد ذكي في سيرفر ديسكورد، ترد بالعربية باختصار وود."},
                        {"role": "user", "content": message.content}
                    ],
                    max_tokens=500
                )
                answer = completion.choices[0].message.content
                await message.reply(answer[:2000])
            except Exception as e:
                await message.reply(f"❌ حدث خطأ في الرد: {e}")

    await bot.process_commands(message)

# ----------------- 4. أمر الرانك (Rank) -----------------
@bot.tree.command(name="rank", description="عرض رانك ومستواك في السيرفر")
async def rank(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    key = f"{interaction.guild.id}_{target.id}"
    data = user_data.get(key, {"xp": 0, "level": 0})
    needed = data["level"] * 300 + 100
    
    img = Image.new('RGB', (1000, 300), '#1a1d2e')
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 980, 280], fill='#23263a')
    
    progress = int((data["xp"] / needed) * 600) if needed > 0 else 0
    draw.rectangle([250, 190, 850, 220], fill='#2a2d45')
    if progress > 0:
        draw.rectangle([250, 190, 250 + progress, 220], fill='#5865F2')
    
    img.save('rank.png')
    await interaction.response.send_message(file=discord.File('rank.png'))

# ----------------- 5. نظام الجيف أواي (Giveaway) -----------------
def parse_duration(duration: str):
    match = re.match(r"(\d+)([dhm])", duration)
    if not match:
        return None
    amount, unit = match.groups()
    amount = int(amount)
    if unit == 'd': return timedelta(days=amount)
    if unit == 'h': return timedelta(hours=amount)
    if unit == 'm': return timedelta(minutes=amount)
    return None

@bot.tree.command(name="giveaway", description="إنشاء مسابقة جيف اواي جديدة")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(interaction: discord.Interaction, duration: str, winners: int, prize: str, channel: discord.TextChannel = None):
    target_channel = channel or interaction.channel
    delta = parse_duration(duration)
    if not delta:
        return await interaction.response.send_message("❌ صيغة الوقت خطأ، استخدم صيغ مثل: 1d أو 2h أو 30m", ephemeral=True)
    
    end_time = datetime.now() + delta
    
    embed = discord.Embed(title="🎉 جيف اواي جديد!", color=0xfaa61a)
    embed.description = f"""
**الجائزة:** {prize}
**عدد الفائزين:** {winners}
**ينتهي في:** <t:{int(end_time.timestamp())}:R>

اضغط على التفاعل 🎉 للمشاركة!
"""
    embed.set_footer(text=f"أنشئ بواسطة {interaction.user}")
    
    await interaction.response.send_message(f"✅ تم إنشاء الجيف اواي في {target_channel.mention}", ephemeral=True)
    msg = await target_channel.send(embed=embed)
    await msg.add_reaction("🎉")
    
    await asyncio.sleep(delta.total_seconds())
    
    try:
        msg = await target_channel.fetch_message(msg.id)
        reaction = discord.utils.get(msg.reactions, emoji="🎉")
        if not reaction:
            return
        
        users = [u async for u in reaction.users() if not u.bot]
        if not users:
            await target_channel.send("❌ انتهى الجيف اواي ولكن لم يشارك أحد!")
            return
        
        selected = random.sample(users, min(winners, len(users)))
        win_embed = discord.Embed(title="🎊 انتهى الجيف اواي!", color=0x00d166)
        win_embed.description = f"**الجائزة:** {prize}\n**الفائزون:** {', '.join([u.mention for u in selected])}"
        
        await target_channel.send(content=" ".join([u.mention for u in selected]) + " مبروك الفوز! 🎉", embed=win_embed)
    except Exception as e:
        print(f"خطأ في الجيف أواي: {e}")

# ----------------- 6. نظام الاقتصاد (Economy & AI Commands) -----------------
@bot.tree.command(name="balance", description="عرض رصيدك أو رصيد شخص آخر")
async def balance(interaction: discord.Interaction, user: discord.User = None):
    target = user or interaction.user
    async with aiosqlite.connect("economy.db") as db:
        async with db.execute("SELECT balance, bank FROM users WHERE user_id = ?", (target.id,)) as cur:
            row = await cur.fetchone()
            bal, bank = row if row else (0, 0)
    
    embed = discord.Embed(color=0x3ba55c)
    embed.set_author(name=target.name, icon_url=target.display_avatar.url)
    embed.add_field(name="💵 المحفظة", value=f"{bal:,} 💰")
    embed.add_field(name="🏦 البنك", value=f"{bank:,} 💰")
    embed.add_field(name="💎 الإجمالي", value=f"{bal+bank:,} 💰")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="daily", description="استلام المكافأة اليومية")
async def daily(interaction: discord.Interaction):
    user_id = interaction.user.id
    current_time = datetime.now().timestamp()
    
    async with aiosqlite.connect("economy.db") as db:
        async with db.execute("SELECT last_daily FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row and row[0] and current_time - row[0] < 86400:
                remaining = int(86400 - (current_time - row[0]))
                hours, remainder = divmod(remaining, 3600)
                minutes = remainder // 60
                return await interaction.response.send_message(f"⏰ لقد استلمت مكافأتك اليومية مسبقاً. انتظر {hours} ساعة و {minutes} دقيقة.", ephemeral=True)
        
        reward = random.randint(500, 1000)
        await db.execute("""
            INSERT INTO users (user_id, balance, last_daily) 
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
            balance = balance + ?, 
            last_daily = ?
        """, (user_id, reward, current_time, reward, current_time))
        await db.commit()
    
    await interaction.response.send_message(f"🎁 مبروك! حصلت على مكافأتك اليومية بقيمة {reward} عملة.")

@bot.tree.command(name="ask", description="اسأل الذكاء الاصطناعي سؤالاً مباشراً")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "أنت مساعد ذكي في سيرفر ديسكورد، ترد بالعربية باختصار وود."},
                {"role": "user", "content": question}
            ],
            max_tokens=500
        )
        answer = response.choices[0].message.content
        
        embed = discord.Embed(color=0x00d166)
        embed.add_field(name="❓ سؤالك", value=question, inline=False)
        embed.add_field(name="🤖 الإجابة", value=answer[:1000], inline=False)
        embed.set_footer(text="بواسطة GPT-4o-mini")
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ حدث خطأ: {e}")

@bot.tree.command(name="translate", description="ترجمة نص إلى اللغة المطلوبة")
async def translate(interaction: discord.Interaction, text: str, to_lang: str = "العربية"):
    await interaction.response.defer()
    try:
        res = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"ترجم النص التالي إلى {to_lang}: {text}"}]
        )
        await interaction.followup.send(f"🌐 **الترجمة:**\n{res.choices[0].message.content}")
    except Exception as e:
        await interaction.followup.send(f"❌ حدث خطأ في الترجمة: {e}")

# ----------------- 7. أوامر الإشراف (Ban & Clear) -----------------
@bot.tree.command(name="ban", description="حظر عضو من السيرفر")
@app_commands.describe(user="العضو المراد حظره", reason="سبب الحظر")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "بدون سبب"):
    await interaction.guild.ban(user, reason=reason)
    embed = discord.Embed(title="🔨 تم حظر العضو", color=0xff4757)
    embed.add_field(name="العضو", value=user.mention, inline=True)
    embed.add_field(name="السبب", value=reason, inline=True)
    embed.add_field(name="بواسطة", value=interaction.user.mention, inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear", description="مسح عدد محدد من الرسائل")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"✅ تم مسح {len(deleted)} رسالة بنجاح.", ephemeral=True)

# تشغيل البوت (ضع التوكن الخاص بك هنا أو في ملف .env للأمان)
bot.run("MTU2MDA0Mjg2MjQwNDQ0NDE5Mg.GlTs31.mdxdXGi8eBBjMR94dZtp9wb5ryjUX747RbePzM")
