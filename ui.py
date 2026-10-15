"""Shared UI helpers: CSS, highlighting, text-to-speech buttons."""
import html
import inspect
import json
import re

import streamlit as st
import streamlit.components.v1 as components

# full-width buttons on any Streamlit version
WIDE = ({"width": "stretch"} if "width" in inspect.signature(st.button).parameters
        else {"use_container_width": True})

CSS = """
<style>
.block-container {padding-top: 4rem; padding-bottom: 3rem; max-width: 680px;}
header[data-testid="stHeader"] {background: transparent; pointer-events: none;}
header[data-testid="stHeader"] * {pointer-events: auto;}
/* top menu as tab buttons */
div[role="radiogroup"]:has(input[type="radio"]) {flex-wrap: wrap; gap: 6px;}
.st-key-page div[role="radiogroup"] label {background:#f3f4f6; border-radius:999px;
       padding:6px 12px; margin:0;}
.st-key-page div[role="radiogroup"] label:has(input:checked) {background:#2563eb;}
.st-key-page div[role="radiogroup"] label:has(input:checked) p {color:#fff; font-weight:700;}
.st-key-page div[role="radiogroup"] label > div:first-child {display:none;}
@media (max-width: 640px) {.block-container {padding-top: 3.5rem;}}
.card {background:#fff; color:#1f2937; border-radius:18px; padding:22px 20px;
       box-shadow:0 2px 12px rgba(0,0,0,.08); margin:6px 0 14px;}
.card .front {font-size:2.3rem; font-weight:700; text-align:center; line-height:1.3;}
.card .front.th {font-size:1.8rem;}
.card .sub {text-align:center; color:#6b7280; font-size:.85rem; margin-bottom:6px;}
.card .ans {font-size:1.6rem; font-weight:700; text-align:center; color:#1d4ed8; margin:10px 0 4px;}
.card hr {border:none; border-top:1px solid #e5e7eb; margin:14px 0;}
.card .ex-en {font-size:1.1rem; margin-bottom:4px;}
.card .ex-en.big {font-size:1.3rem; line-height:1.6;}
.card .ex-th {font-size:1rem; color:#4b5563;}
.card .q {text-align:center; color:#374151; margin-top:10px;}
.card .hint {text-align:center; color:#b45309; margin-top:8px; font-size:.95rem;}
.card b.hl {color:#b45309;}
.blank {display:inline-block; min-width:90px; border-bottom:3px solid #2563eb; color:#2563eb;
        text-align:center; font-weight:700;}
.diff {font-size:1.1rem; line-height:1.9;}
.diff .ok {color:#15803d;}
.diff .bad {color:#dc2626; text-decoration:line-through;}
.diff .miss {color:#dc2626; text-decoration:underline; font-weight:700;}
.pill {display:inline-block; padding:2px 10px; border-radius:999px; font-size:.75rem;
       background:#eef2ff; color:#3730a3; margin-right:4px;}
div[data-testid="stMetricValue"] {font-size:1.6rem;}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def hl_en(sentence, target):
    s = html.escape(sentence)
    if target:
        s = re.sub(r"(?<![A-Za-z])" + re.escape(html.escape(target)) + r"(?![A-Za-z])",
                   lambda m: f"<b class='hl'>{m.group(0)}</b>", s, count=1, flags=re.I)
    return s


def hl_th(sentence, meaning):
    s = html.escape(sentence)
    for part in sorted((p.strip() for p in meaning.split("/")), key=len, reverse=True):
        if part and part in sentence:
            return s.replace(html.escape(part), f"<b class='hl'>{html.escape(part)}</b>", 1)
    return s


def card_back_html(w):
    return (f"<div class='ex-en'>{hl_en(w['example_en'], w['target'])}</div>"
            f"<div class='ex-th'>{hl_th(w['example_th'], w['meaning_th'])}</div>")


def speak_row(items):
    """items: list of (text, label, rate). Uses the browser's built-in speech (no API)."""
    def btn(text, label, rate):
        js = html.escape(json.dumps(text), quote=True)
        return (f'<button onclick="speechSynthesis.cancel();const u=new SpeechSynthesisUtterance({js});'
                f'u.lang=\'en-US\';u.rate={rate};speechSynthesis.speak(u);">{label}</button>')
    components.html(f"""
    <style>
      body{{margin:0}} div{{display:flex;gap:8px}}
      button{{flex:1;padding:10px;border-radius:10px;border:1px solid #d1d5db;background:#f9fafb;
             font-size:15px;cursor:pointer}}
    </style>
    <div>{''.join(btn(*i) for i in items)}</div>""", height=48)


def speak_buttons(word, sentence, rate):
    speak_row([(word, "🔊 คำศัพท์", rate), (sentence, "🔊 ประโยค", rate)])
