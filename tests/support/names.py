"""Schedule names by hand from the agreed rule (plan 261122, D1 and D4): what `--name` takes as given, what it refuses with a word its reason must carry, and the names Windows reserves. Shared by the tests that drive `schedule` and the one that reads its help."""

ACCEPTED = [
    "261128_SS_외국인순매수",
    "270225_NVDA_Q4 실적 (가이던스)",
    "💎 weekly",
    "👩‍💻 review",  # an emoji joined by U+200D, which a name may hold
    "a#b%c",
    ".hidden",
    "가" * 80,  # 80 UTF-16 units
    "😀" * 40,  # 80 UTF-16 units: an emoji is two
    "nightly-review",  # a name 0.2.0 took
    "a+b&c'd,e@f=g~h!(i)[j]{k}$l;m^n`o",
    "\U0001fae9 face",  # Unicode 16: the Unicode tables of Pythons before 3.14 do not know it
    "x\U0002fff0",  # a code point no table knows yet stands for a character newer than the Python reading it
]

REFUSED = [
    ("가" * 81, "80"),
    ("😀" * 41, "80"),
    ("a/b", "`/`"),
    ("Q4: x?", "`:`"),
    ("a|b", "`|`"),
    ("a\\b", "`\\`"),
    ('say "x"', '`"`'),
    ("a*b", "`*`"),
    ("a<b", "`<`"),
    ("a>b", "`>`"),
    ("why?", "`?`"),
    ("x${{y", "`${{`"),
    ("-draft", "`-`"),
    (" lead", "space"),
    ("trail ", "space"),
    ("trail.", "`.`"),
    ("tab\there", "U+0009"),
    ("line\nbreak", "U+000A"),
    ("zero​width", "U+200B"),
    ("no break", "U+00A0"),
    ("right‮left", "U+202E"),
    ("line separator", "U+2028"),
    ("privateuse", "U+E000"),
    ("non\ufdd0char", "U+FDD0"),  # noncharacters stay unassigned in every Unicode version
    ("non\U0002fffechar", "U+2FFFE"),
]

# The part before the first dot is a device name on Windows, whatever its case.
RESERVED = ["con", "NUL", "prn", "com1", "LPT9", "aux.backup", "COM¹"]
NOT_RESERVED = ["console", "com10", "nul-check", "lpt"]
