"""
Per-language string table for the Telegram bot.

Why this exists: land_steward.preferred_language (db/schema.sql, free
TEXT, default 'juba_arabic') has existed since the original registration
design but telegram_inbound.py never read it -- every reply was a bare
English string hardcoded at the call site. This is the swappable
structure that fixes that, without yet changing what any user actually
receives (English stays English until 'jba' entries are real).

Script choice -- Latin, not Arabic/RTL: South Sudan's 2011 transitional
constitution makes English the sole official language; Juba Arabic has
no standardized orthography but the linguistic literature (SIL
International's orthography work, the 2005 Kamuus ta Arabi Juba wa
Ingliizi dictionary) and every real South Sudan digital service found
during research (JunubSMS, MTN's apps) use Latin script, not Arabic
script. See conversation history for the full research and sourcing --
this module assumes that conclusion but does not re-litigate it.

Translation discipline: 'jba' entries are None -- deliberately left
unfilled rather than machine-translated or guessed, same Scientific
Evidence rule this project applies to a crop-suitability score or an
FX rate (see db/schema.sql's input_requirement migration note: a number
without a real source is worse than no number). get_string() falls back
to English for any 'jba' key that's still None. Filling these in is a
content-sourcing task for someone who actually speaks Juba Arabic
(flagged to Philip Pitia / Edward Lumani), not a coding task.

What does NOT get translated: interpolated data -- a farmer's name, a
crop name, a price, a date -- is passed in as format arguments and
inserted as-is regardless of language. Crop names in particular are
live lookup keys elsewhere in the system (crop_dictionary_entry.crop_name);
translating them in a reply would desync what's displayed from what a
user needs to type back into PRICE <crop>.
"""
from typing import Optional

DEFAULT_LANGUAGE = "en"

# Maps land_steward.preferred_language's free-text stored value to a
# language code below. TEXT column, no CHECK constraint (see
# db/schema.sql) -- any string could be stored, so this is a lookup
# with a safe default, never a crash on an unrecognized value.
PREFERRED_LANGUAGE_TO_CODE = {
    "juba_arabic": "jba",
    "english": "en",
}


def language_code_for(preferred_language: Optional[str]) -> str:
    """land_steward.preferred_language -> a STRINGS language code, defaulting to English for anything unset or unrecognized."""
    return PREFERRED_LANGUAGE_TO_CODE.get(preferred_language, DEFAULT_LANGUAGE)


# One entry per distinct user-facing message in telegram_inbound.py.
# {name}-style placeholders are filled via str.format() in get_string()
# -- they carry DATA (a full_name, a crop, a price), never UI copy, so
# they're identical across languages and don't need a per-language key.
STRINGS = {
    "menu_text": {
        "en": "1. Link my phone number\n2. Check today's price\n3. Check my registration status\nReply with a number.",
        "jba": None,
    },
    "staff_auth_required": {
        "en": "This action requires CORWADO staff authorization. Send STAFF <phone number> to link your account, or contact your program coordinator.",
        "jba": None,
    },
    "gender_menu": {
        "en": "Gender? 1=female 2=male 3=other 4=prefer not to say (numbers or words both work, or reply SKIP)",
        "jba": None,
    },
    "gender_not_recognized": {
        "en": "Didn't recognize that. {menu}",
        "jba": None,
    },

    "register_usage": {
        "en": "Usage: REGISTER <phone number>",
        "jba": None,
    },
    "register_not_found": {
        "en": "No registration found for that phone number. Ask your Digital Champion to register you first.",
        "jba": None,
    },
    "register_phone_linked_elsewhere": {
        "en": "This phone is already linked to a different Telegram account — contact your Digital Champion.",
        "jba": None,
    },
    "register_chat_linked_elsewhere": {
        "en": "This Telegram account is already linked to a different farmer record ({name}) — contact your Digital Champion if this phone number should be linked instead.",
        "jba": None,
    },
    "register_linked": {
        "en": "Linked. You're registered as {name}. Reply BOUNDARY to trace your farm now.",
        "jba": None,
    },
    "register_phone_prompt": {
        "en": "Send your phone number.",
        "jba": None,
    },

    "staff_usage": {
        "en": "Usage: STAFF <phone number>",
        "jba": None,
    },
    "staff_not_found": {
        "en": "No staff authorization found for that phone number. Contact your program coordinator.",
        "jba": None,
    },
    "staff_suspended": {
        "en": "Your access has been suspended. Contact your program coordinator.",
        "jba": None,
    },
    "staff_phone_linked_elsewhere": {
        "en": "This phone is already linked to a different Telegram account — contact your program coordinator.",
        "jba": None,
    },
    "staff_linked": {
        "en": "Linked. You're authorized as CORWADO staff: {name}.",
        "jba": None,
    },

    "price_usage": {
        "en": "Usage: PRICE <crop>",
        "jba": None,
    },
    "price_crop_not_tracked": {
        "en": "No crop named '{crop}' is tracked.",
        "jba": None,
    },
    "price_no_price_yet": {
        "en": "No price recorded yet for {crop}.",
        "jba": None,
    },
    "price_result": {
        "en": "{crop}: {price} SSP/{unit} at {location} (recorded {date})",
        "jba": None,
    },

    "status_unregistered": {
        "en": "You're not registered yet. Send REGISTER <phone> to link your account.",
        "jba": None,
    },
    "status_registered": {
        "en": "{name} — registered, linked via Telegram. Cooperative: {coop}.",
        "jba": None,
    },

    "crop_menu_header": {
        "en": "Which crop?",
        "jba": None,
    },
    "crop_not_recognized": {
        "en": "Didn't recognize that crop. {menu}",
        "jba": None,
    },

    "boundary_no_farmer_found": {
        "en": "No farmer found with phone number {phone}.",
        "jba": None,
    },
    "boundary_usage": {
        "en": "Usage: BOUNDARY <farmer phone number>",
        "jba": None,
    },
    "boundary_link": {
        "en": "Open this link to trace {name}'s farm boundary (expires in {minutes} minutes):\n{link}",
        "jba": None,
    },
    "boundary_self_link": {
        "en": "Open this link to trace your farm boundary (expires in {minutes} minutes):\n{link}",
        "jba": None,
    },
    "boundary_self_existing_confirm": {
        "en": "You already have a farm boundary on file ({acres} acres). Reply YES to add another, or NO to cancel.",
        "jba": None,
    },
    "boundary_self_existing_confirm_retry": {
        "en": "Reply YES to add another, or NO to cancel.",
        "jba": None,
    },
    "boundary_self_cancelled": {
        "en": "Cancelled — no changes made.",
        "jba": None,
    },
    "boundary_large_area_confirm": {
        "en": "The boundary just drawn for {name} covers about {ha} hectares — much larger than a typical smallholder plot. Reply YES to save it anyway, or NO to redraw.",
        "jba": None,
    },
    "boundary_large_area_confirm_retry": {
        "en": "Reply YES to save it anyway, or NO to redraw.",
        "jba": None,
    },
    "boundary_large_area_saved": {
        "en": "Boundary saved for {name}: {area} (confirmed as unusually large).",
        "jba": None,
    },
    "boundary_large_area_expired": {
        "en": "That confirmation has expired — send BOUNDARY again to draw a new one.",
        "jba": None,
    },
    "boundary_large_area_redraw": {
        "en": "Let's redraw it. Open this link to trace the boundary again (expires in {minutes} minutes):\n{link}",
        "jba": None,
    },

    "new_farmer_name_prompt": {
        "en": "Full name of the farmer?",
        "jba": None,
    },
    "new_farmer_phone_prompt": {
        "en": "Farmer's phone number?",
        "jba": None,
    },
    "new_farmer_phone_usage": {
        "en": "Usage: send a phone number, e.g. 0912345678",
        "jba": None,
    },
    "new_farmer_dup_confirm": {
        "en": "A farmer named {name} is already registered with that number. Reply YES to create a new record anyway (e.g. two people share a phone), or NO to cancel.",
        "jba": None,
    },
    "new_farmer_dup_confirm_retry": {
        "en": "Reply YES to create anyway, or NO to cancel.",
        "jba": None,
    },
    "new_farmer_cancelled": {
        "en": "Cancelled — no farmer created.",
        "jba": None,
    },
    "new_farmer_created": {
        "en": "Created: {name}. Reply BOUNDARY to trace their farm now, or DONE to finish.",
        "jba": None,
    },

    # Self-service onboarding (unregistered, unlinked chat's first
    # contact) -- see telegram_inbound.py's _handle_onboard_* functions.
    # Reuses gender_menu/gender_not_recognized/GENDER_CHOICES verbatim
    # for the gender step; these are the new steps that have no existing
    # collection UX to reuse (is_youth/has_disability were previously
    # only ever written as their column defaults, never actually asked).
    "onboard_welcome": {
        "en": (
            "Welcome to CORWADO! Let's get you registered as a farmer — "
            "I'll ask a few quick questions (reply MENU any time to cancel).\n\n"
            "Already registered with CORWADO? Send REGISTER followed by "
            "your phone number instead.\n\n"
            "What's your full name?"
        ),
        "jba": None,
    },
    "onboard_name_prompt": {
        "en": "What's your full name?",
        "jba": None,
    },
    "onboard_phone_prompt": {
        "en": "What's your phone number?",
        "jba": None,
    },
    "onboard_link_existing_confirm": {
        "en": "We found an existing record under this phone number ({name}). Reply YES to link your Telegram to that record, or NO if that's not you.",
        "jba": None,
    },
    "onboard_link_existing_confirm_retry": {
        "en": "Reply YES to link, or NO if that's not you.",
        "jba": None,
    },
    "onboard_link_existing_needs_staff": {
        "en": "This phone number is already registered to {name}. If that's not you, please contact your Digital Champion or a CORWADO staff member — they can help register you correctly.",
        "jba": None,
    },
    "onboard_created": {
        "en": "You're registered, {name}!",
        "jba": None,
    },
    "onboard_youth_prompt": {
        "en": "Are you a youth? Reply YES or NO, or SKIP.",
        "jba": None,
    },
    "onboard_choice_not_recognized": {
        "en": "Didn't recognize that. {menu}",
        "jba": None,
    },
    "onboard_disability_prompt": {
        "en": "Do you have a disability that affects how we should contact you (for example, a hearing or vision difficulty)? Reply YES or NO, or SKIP.",
        "jba": None,
    },
    "onboard_disability_notes_prompt": {
        "en": "Would you like to describe it? For example: 'hard of hearing' or 'low vision, prefers audio.' Type your answer, or reply SKIP to leave it blank.",
        "jba": None,
    },

    # Services menu (already-registered/linked farmer's fallback,
    # replacing the generic menu_text for this audience) and its items.
    "services_menu_text": {
        "en": (
            "1. Check today's price\n"
            "2. My registration status\n"
            "3. Farm diagnostic (FarmLab)\n"
            "4. My input costs\n"
            "5. Extension advice (coming soon)\n"
            "6. Update my farm boundary\n"
            "Reply with a number."
        ),
        "jba": None,
    },
    "no_boundary_yet": {
        "en": "You haven't traced your farm boundary yet. Reply BOUNDARY to do that first.",
        "jba": None,
    },
    "farmlab_not_ready": {
        "en": "No FarmLab diagnostic on file yet for your farm. Ask your Digital Champion, or use the CORWADO web dashboard, to run your first check.",
        "jba": None,
    },
    "boq_no_season": {
        "en": "No planting season on file for your farm yet. Ask your Digital Champion to add one, or check back after your next planting.",
        "jba": None,
    },
    "boq_empty": {
        "en": "No cost breakdown on file yet for this season.",
        "jba": None,
    },
    "boq_header": {
        "en": "Input costs for your {crop} season ({season_label}):",
        "jba": None,
    },
    "boq_no_financing": {
        "en": "No financing recorded yet for these costs.",
        "jba": None,
    },
    "extension_coming_soon": {
        "en": "This service isn't available yet on Telegram — check back soon!",
        "jba": None,
    },
}


def get_string(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """
    STRINGS[key][lang], falling back to STRINGS[key]['en'] when the
    requested language's entry is missing or still a None placeholder.
    Formats with **kwargs via str.format() when given.

    Raises KeyError if `key` itself isn't in STRINGS -- a typo'd key is
    a programming error that should fail loudly in development, not
    silently send a blank/broken reply to a real farmer.
    """
    entry = STRINGS[key]
    text = entry.get(lang) or entry[DEFAULT_LANGUAGE]
    return text.format(**kwargs) if kwargs else text
