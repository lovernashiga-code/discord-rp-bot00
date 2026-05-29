# main.py - ปรับเพื่อใส่ใน GitHub / deploy (อย่าใส่ token ลงในโค้ด)
import os
import sys
import json
import random
import datetime
import math
import typing
import gc

import discord
from discord.ext import commands
from discord.ui import View, Select

# (Optional) lightweight keep-alive server for platforms that need it (Replit etc.)
from flask import Flask
from threading import Thread

# ---------- server เพื่อกันบอทหลับ (เรียกเฉพาะเมื่อจำเป็น) ----------
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def server_on():
    # เรียกเฉพาะบน platform ที่ต้องให้ endpoint ตอบกลับ (เช่น Replit)
    try:
        Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    except Exception:
        pass


# ---------- Intents แบบจำเป็น (ลดการใช้ RAM) ----------
intents = discord.Intents.default()
intents.message_content = True
# อย่าเปิด intents.members ถ้าไม่จำเป็น เพราะจะทำให้ member cache ใหญ่และกินแรม
# intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, max_messages=100)


# ---------- ฟังก์ชันอ่าน /proc เพื่อดู RAM ทั้งระบบ  ----------
def get_ram_usage():
    try:
        with open("/proc/meminfo", "r") as f:
            meminfo = f.read()
        mem_total = int([x for x in meminfo.split("\n") if "MemTotal" in x][0].split()[1]) / 1024
        mem_free = int([x for x in meminfo.split("\n") if "MemAvailable" in x][0].split()[1]) / 1024
        mem_used = mem_total - mem_free
        return mem_used, mem_total
    except Exception:
        return None, None


# ---------- Lazy-loaded JSON (ป้องกันโหลดไฟล์ใหญ่ตอน start) ----------
ITEMS_CACHE = None
def load_json(filename):
    if not os.path.exists(filename):
        return {}
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)

def get_items():
    global ITEMS_CACHE
    if ITEMS_CACHE is None:
        ITEMS_CACHE = load_json("item_effects.json")
    return ITEMS_CACHE


# ---------- คำสั่ง !ram ให้บอทตอบ RAM ของตัวเอง (อ่านจาก /proc/<pid>/status) ----------
@bot.command(name="ram")
async def ram(ctx):
    pid = os.getpid()
    try:
        with open(f"/proc/{pid}/status", "r") as f:
            data = f.read()
        vmrss_lines = [x for x in data.split("\n") if "VmRSS" in x]
        if vmrss_lines:
            vmrss_line = vmrss_lines[0]
            ram_kb = int(vmrss_line.split()[1])
            ram_mb = ram_kb / 1024
            await ctx.send(f"RAM ของบอท: {ram_mb:.2f} MB")
            return
    except Exception:
        pass

    # fallback: บอก RAM ทั้งเครื่อง (ถ้า /proc/<pid>/status อ่านไม่ได้)
    mem_used, mem_total = get_ram_usage()
    if mem_used is not None:
        await ctx.send(f"RAM ทั้งเครื่องใช้ไป: {mem_used:.2f} MB / {mem_total:.2f} MB")
    else:
        await ctx.send("ไม่สามารถอ่านข้อมูล RAM จากระบบได้")


# ---------- ข้อมูลแผนที่ / กำหนดค่าต่าง ๆ ----------
MAP_LOCATIONS = {
    "🏰มหานครโรมิรุส": 1425621138461167788,
    "🟢 เขตเเดนสีเขียว": 1426048448632717404,
    "🏔️ เทือกเขาคีริน": 1426048402310959124,
    "🌊 ผืนทะเลใต้": 1426048324636508222,
    "🔇 ดินเเดนสงัด": 1426048278973382728,
    "🌳 ป่าศักดิ์สิทธิ์": 1426048229287530547,
    "💧 ทะเลสาบเวทย์มนต์": 1426048187113803776,
    "🕸️ นครร้างโบราณ": 1426048129983320194,
    "💀 เขตเแดนต้องห้าม": 1426048047426568336
}

FORBIDDEN_ZONE = "💀 เขตเแดนต้องห้าม"
FORBIDDEN_CHANCE = 10  # % โอกาสโดนดูดเข้าเขตต้องห้าม
ESCAPE_SUCCESS_RATE = 30  # % โอกาสหนีออกสำเร็จ

FORBIDDEN_EVENTS = [
    "เสียงกระซิบแผ่วเบาดังขึ้นในหัวคุณ... มันเรียกชื่อของคุณซ้ำแล้วซ้ำเล่า 🌀",
    "พื้นดินสั่นสะเทือน... และรอยแยกสีดำเริ่มก่อตัวใต้เท้าคุณ ⚫",
    "คุณเห็นเงาเคลื่อนไหวอยู่ในหมอก แต่เมื่อหันไปมอง... มันหายไป 💨",
    "เลือดจากจมูกของคุณหยดลงพื้น และซึมหายราวกับผืนดินดูดกลืนมันไว้ 🩸"
]


# =============================================================
# 🌍 ระบบเมนูเดินทาง (TravelSelect) — ไม่มีการโหลดข้อมูลหนักใน constructor
# =============================================================
class TravelSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=name, description="เดินทางไปยังพื้นที่นี้", emoji=name[0])
            for name in MAP_LOCATIONS.keys() if name != FORBIDDEN_ZONE
        ]
        super().__init__(placeholder="เลือกสถานที่ที่จะเดินทางไป...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return await interaction.response.send_message("❌ ไม่พบข้อมูลสมาชิก", ephemeral=True)

        selected = self.values[0]
        msg = ""

        # สุ่มโดนดูดเข้าเขตต้องห้าม
        if random.randint(1, 100) <= FORBIDDEN_CHANCE:
            selected = FORBIDDEN_ZONE
            event_msg = random.choice(FORBIDDEN_EVENTS)
            msg = (
                f"💀 **รถม้าคุณชะงักงันระหว่างทางบางสิ่งในเงามืดดึงคุณลงไป...**\n"
                f"{event_msg}\n\n"
                f"คุณหลุดเข้า **เขตแดนต้องห้าม** โดยไม่รู้ตัว! (หากต้องการหลบหนีใช้คำสั่ง `!หลบหนี`)"
            )
        else:
            msg = f"✅ ขอให้แสงคุ้มครองท่าน เดินทางไป **{selected}** สำเร็จ!"

        new_role = interaction.guild.get_role(MAP_LOCATIONS.get(selected))
        if not new_role:
            return await interaction.response.send_message("❌ ไม่พบ Role สำหรับสถานที่นี้", ephemeral=True)

        # ลบ role เดิมที่เป็นสถานที่ก่อนหน้า
        for r in list(member.roles):
            if r.id in MAP_LOCATIONS.values():
                try:
                    await member.remove_roles(r)
                except Exception:
                    pass

        # เพิ่ม role ใหม่
        try:
            await member.add_roles(new_role)
        except Exception:
            pass

        await interaction.response.send_message(msg, ephemeral=True)


class TravelView(discord.ui.View):
    def __init__(self):
        # ตั้ง timeout เพื่อให้ View ถูกเก็บทิ้งอัตโนมัติ (ลดการใช้งานหน่วยความจำ)
        super().__init__(timeout=180)
        self.add_item(TravelSelect())


@bot.command(name="เดินทาง")
async def เดินทาง(ctx):
    """เปิดเมนูเดินทางไปยังพื้นที่ต่าง ๆ"""
    embed = discord.Embed(
        title="🗺️ เดินทาง",
        description="เลือกสถานที่จากเมนูด้านล่างเพื่อเดินทางไป!",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed, view=TravelView())


# =============================================================
# 🏃 คำสั่ง: หลบหนีจากเขตต้องห้าม (รองรับ Thread)
# =============================================================
@bot.command(name="หลบหนี")
async def หลบหนี(ctx):
    """พยายามหนีออกจากเขตแดนต้องห้าม"""
    # ตรวจสอบบริบทของคำสั่ง (ให้ทำงานได้ทั้งใน thread และ channel)
    if hasattr(ctx.channel, "parent") and ctx.channel.parent is not None:
        guild = ctx.channel.parent.guild or ctx.guild
    else:
        guild = ctx.guild

    if not guild:
        return await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะในเซิร์ฟเวอร์")

    member = guild.get_member(ctx.author.id)
    if not member:
        return await ctx.send("❌ ไม่พบข้อมูลผู้ใช้ในเซิร์ฟเวอร์นี้")

    forbidden_role = guild.get_role(MAP_LOCATIONS.get(FORBIDDEN_ZONE))
    if not forbidden_role:
        return await ctx.send("❌ ไม่พบ role ของเขตแดนต้องห้ามในระบบ")

    if forbidden_role not in member.roles:
        return await ctx.send("❌ คุณไม่ได้อยู่ในเขตแดนต้องห้าม!")

    success = random.randint(1, 100) <= ESCAPE_SUCCESS_RATE
    if success:
        try:
            await member.remove_roles(forbidden_role)
        except Exception:
            pass

        new_place = random.choice([loc for loc in MAP_LOCATIONS.keys() if loc != FORBIDDEN_ZONE])
        new_role = guild.get_role(MAP_LOCATIONS.get(new_place))

        if new_role:
            try:
                await member.add_roles(new_role)
            except Exception:
                pass

        await ctx.send(
            f"🏃‍♂️ คุณวิ่งสุดชีวิต ฝ่าหมอกหนาทึบ...\n"
            f"แสงสว่างเจิดจ้าแผ่เข้ามา และคุณพบว่าตัวเองอยู่ที่ **{new_place}**!"
        )
    else:
        fail_msg = random.choice([
            "เสียงหัวเราะเย้ยหยันดังขึ้นในหัวคุณ...",
            "หมอกมืดกลืนร่างคุณกลับไปยังพื้นดิน...",
            "ขาคุณจมหายไปในดินสีดำ... การหนีล้มเหลว!"
        ])
        await ctx.send(f"❌ {fail_msg}\nคุณยังคงติดอยู่ใน **เขตแดนต้องห้าม** 💀")


# =============================================================
# 👆 คำสั่ง: !กด — แสดงชื่อผู้กดปุ่ม
# =============================================================
class PresserButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="กดที่นี่!", style=discord.ButtonStyle.primary, emoji="👆")

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        display_name = user.display_name if hasattr(user, "display_name") else user.name
        await interaction.response.send_message(
            f"👆 **{display_name}** (`{user.name}`) ได้กดปุ่มนี้!",
            ephemeral=False
        )


class PresserView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(PresserButton())


@bot.command(name="กด")
async def กด(ctx):
    """ส่งปุ่มที่เมื่อกดแล้วจะแสดงชื่อผู้กด"""
    embed = discord.Embed(
        title="👆 กดปุ่ม",
        description="ใครกดปุ่มนี้บ้าง? ลองกดดูสิ!",
        color=discord.Color.blurple()
    )
    await ctx.send(embed=embed, view=PresserView())


# =============================================================
# on_ready
# =============================================================
@bot.event
async def on_ready():
    print(f"✅ บอทออนไลน์แล้วในชื่อ {bot.user}")

    # แสดง RAM เบื้องต้นเมื่อบอทขึ้น
    mem_used, mem_total = get_ram_usage()
    if mem_used is not None:
        print(f"RAM ใช้ไป: {mem_used:.2f} MB / {mem_total:.2f} MB")
    # เรียกเก็บขยะเพื่อพยายามคืน memory ที่ไม่ได้ใช้
    gc.collect()


# เรียก server_on() เฉพาะถ้าคุณต้องการ (เช่น Replit)
# ถ้าจะ deploy บน Railway สามารถคอมเมนต์บรรทัดนี้ออกได้
# server_on()


# =============================================================
# รันบอทแบบปลอดภัย: อ่าน token จาก environment variable เท่านั้น
# =============================================================

if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        print("ERROR: BOT_TOKEN environment variable ไม่ถูกตั้งค่า! กรุณาตั้งค่าใน GitHub/Host (อย่าใส่ token ในโค้ด)")
        sys.exit(1)
    bot.run(TOKEN)
