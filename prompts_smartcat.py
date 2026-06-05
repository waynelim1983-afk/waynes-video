# C:\projects\YT\amazon\prompts_smartcat.py
# Smart Cat Slave Daily Life — 動態影片提示詞庫
#
# 所有 prompt 為 template 格式，變數由 fill_prompt() 動態填入：
#   {product_name}   — 產品全名
#   {key_feature}    — 產品最重要特色
#   {color}          — 產品顏色
#   {size}           — 尺寸描述
#   {cat_breed}      — 貓咪品種（隨機）
#   {setting}        — 場景（隨機）
#
# 同一類別的同一產品每次生影，因 cat_breed / setting 隨機，畫面都不同。

import random
import datetime

# ── 隨機填充池 ───────────────────────────────────────────────
CAT_BREEDS = [
    "tabby", "ginger tabby", "calico", "black-and-white tuxedo",
    "white Persian", "Maine Coon", "Siamese", "British Shorthair",
    "orange tabby", "tortoiseshell",
]

SETTINGS = [
    "modern minimalist bathroom",
    "cozy sun-lit kitchen",
    "Scandinavian-style living room",
    "warm apartment with hardwood floors",
    "bright clean laundry room",
    "contemporary open-plan home",
    "Japanese-inspired tatami room",
    "industrial-chic loft apartment",
]

# 相機語言 — 適用所有模型（來源：community-prompt-patterns 研究整理）
CAMERA_MOVES = [
    "slow dolly-in",
    "gentle tracking shot",
    "handheld follow",
    "static wide shot",
    "low-angle close-up",
    "overhead bird's-eye",
    "smooth crane reveal",
    "slow push-in",
    "eye-level medium shot",
    "rack focus pull",
]

# 導演風格視覺 token — 主力用於 Veo3（Sora/Veo 效果最好）
# 來源：director-style-library.md
DIRECTOR_STYLES = [
    "warm color palette soft bokeh",
    "symmetrical composition pastel tones",
    "naturalistic light shallow depth of field",
    "neon-tinged warm shadows cinematic grain",
    "clean commercial high-key lighting",
    "golden hour practical light intimate feel",
    "moody teal-and-orange color grade",
    "bright airy lifestyle editorial style",
]

# ── 中文提示詞模板 — 專給 Wan2.x（中文提示效果顯著優於英文）───
# 研究來源：community-prompt-patterns.md — "Wan 2.6/2.7: Chinese prompts outperform English"
PROMPTS_ZH: dict[str, list[str]] = {

    "litter_box": [
        "一隻{cat_breed_zh}貓自信地走進{color}色的{product_name}，{key_feature_zh}，"
        "{setting_zh}，晨光柔和，{camera_move_zh}，9:16 垂直構圖",

        "{size_zh}尺寸的{color}色{product_name}特寫：{key_feature_zh}，"
        "30秒完成全自動清潔，貓砂恢復清新，零人力，{setting_zh}背景，9:16 垂直",

        "分割畫面：{cat_breed_zh}貓的主人悠閒地躺在沙發上滑手機，"
        "{setting_zh}角落的{color}色{product_name}靜靜完成{key_feature_zh}，"
        "零人力介入，9:16 垂直短片",
    ],

    "smart_feeder": [
        "一隻{cat_breed_zh}貓豎起耳朵衝過{setting_zh}，"
        "{color}色{product_name}準時出糧，{key_feature_zh}，黃金時段光線，9:16 垂直",

        "慢動作特寫：{size_zh}{color}色{product_name}出糧瞬間——"
        "貓糧畫出完美弧線落入碗中，一隻{cat_breed_zh}貓的眼睛追蹤每一粒，"
        "{setting_zh}，柔和棚燈，9:16 垂直",

        "兩隻貓在{setting_zh}同時進食——一隻{cat_breed_zh}和一隻橘貓——"
        "{size_zh}{product_name}，{key_feature_zh}確保各得其份，不打架，暖光，9:16 垂直",
    ],

    "water_fountain": [
        "一隻優雅的{cat_breed_zh}貓從{color}色{product_name}飲水，"
        "{key_feature_zh}產生溫柔水流，貓咪明顯更喜歡，{setting_zh}，淺景深，9:16 垂直",

        "極致慢動作：{size_zh}{color}色{product_name}水流特寫，{key_feature_zh}清晰可見——"
        "一隻{cat_breed_zh}貓的舌頭輕柔舔舐每道水流，水珠在{setting_zh}光線下閃耀，9:16 垂直",

        "對比鏡頭：{cat_breed_zh}貓對普通水碗嗤之以鼻，然後興奮地衝向{color}色{product_name}——"
        "{key_feature_zh}決定了一切，{setting_zh}，9:16",
    ],

    "pet_camera": [
        "手機螢幕顯示{product_name}直播畫面——{cat_breed_zh}貓在{setting_zh}玩耍，"
        "{key_feature_zh}追蹤每個動作，遠端主人看著笑開懷，9:16 垂直",

        "{color}色{product_name}順暢旋轉360度，追蹤一隻{cat_breed_zh}貓在{setting_zh}跑跳，"
        "{key_feature_zh}完美捕捉每個瞬間，{camera_move_zh}，9:16 垂直短片",

        "夜視畫面：{product_name}拍下{cat_breed_zh}貓在漆黑{setting_zh}中靜悄悄巡邏——"
        "{key_feature_zh}以清晰綠色夜視呈現每個細節，氛圍感十足，9:16 垂直",
    ],

    "gps_tracker": [
        "一隻{cat_breed_zh}貓戴著{color}色{product_name}項圈，"
        "自信地探索陽光庭院——手機APP顯示{key_feature_zh}即時更新，主人在家放鬆，9:16 垂直",

        "手機螢幕特寫：{product_name}地圖APP——閃爍光點跟著{cat_breed_zh}貓在街區遊走，"
        "{key_feature_zh}精確定位，主人{setting_zh}輕鬆坐著，9:16",

        "逃跑警報：手機震動跳出{product_name}通知——主人打開APP，"
        "{key_feature_zh}顯示{cat_breed_zh}貓在三條街外，走直線接回家，9:16 垂直",
    ],

    "cat_toy": [
        "一隻{cat_breed_zh}貓在{setting_zh}全速衝刺，追著{color}色{product_name}——"
        "{key_feature_zh}永遠快一步，純粹的狩獵本能，慢動作，9:16 垂直",

        "{product_name}在{setting_zh}自行運作，{cat_breed_zh}貓繞著它著魔般打轉——"
        "{key_feature_zh}每次都讓貓措手不及，主人在沙發上笑彎腰，9:16 垂直",

        "前後對比：{cat_breed_zh}貓癱在沙發上紋絲不動——然後{product_name}啟動{key_feature_zh}，"
        "同一隻貓秒變衝刺獵手，{setting_zh}，9:16 垂直",
    ],

    "grooming": [
        "一隻{cat_breed_zh}貓享受著{color}色{product_name}的梳理，"
        "眼睛半闔陶醉其中——{key_feature_zh}輕鬆梳透毛髮，{setting_zh}，9:16",

        "慢動作特寫：{key_feature_zh}——{size_zh}{color}色{product_name}"
        "滑過{cat_breed_zh}貓的毛髮，一道絲滑動作帶出大量浮毛，{setting_zh}背景，9:16 垂直",

        "梳前梳後對比：{cat_breed_zh}貓毛亂如草堆——{product_name}{key_feature_zh}後，"
        "同一隻貓毛色如鏡，{setting_zh}，柔和棚燈，9:16",
    ],

    "cat_bed": [
        "一隻{cat_breed_zh}貓謹慎地靠近新的{color}色{product_name}，"
        "嗅遍每個角落，再緩緩踏入蜷縮成一球——{key_feature_zh}立刻征服貓心，{setting_zh}，9:16 垂直",

        "極致特寫：{cat_breed_zh}貓在{size_zh}{color}色{product_name}中酣睡——"
        "{key_feature_zh}打造完美睡眠環境，柔和暖光，貓鬚微微顫動，9:16",

        "一隻毛茸茸的{cat_breed_zh}貓在{color}色{product_name}上用力踩奶，"
        "然後盤成完美螺旋——{key_feature_zh}維持那份溫暖形狀，{setting_zh}，黃金時段，9:16 垂直",
    ],

    "lifestyle": [
        "一隻{cat_breed_zh}貓在{setting_zh}享受全自動化生活剪輯："
        "{product_name}完美運作，{key_feature_zh}全包辦——零人力，晨光暖意，9:16 垂直",

        "一隻{cat_breed_zh}貓端坐在{setting_zh}，四周智慧裝置閃爍微光，"
        "{color}色{product_name}靜靜運作——顯然貓才是真正的主人，9:16 垂直短片",
    ],
}

# 中文貓咪品種對應
CAT_BREEDS_ZH = [
    "虎斑", "橘虎斑", "三花", "黑白賓士",
    "白色波斯", "緬因貓", "暹羅", "英國短毛",
    "橘貓", "玳瑁",
]

# 中文場景對應
SETTINGS_ZH = [
    "現代極簡浴室",
    "陽光灑落的溫馨廚房",
    "北歐風格客廳",
    "木地板溫馨公寓",
    "明亮整潔的洗衣房",
    "現代開放式格局住宅",
    "日式榻榻米房間",
    "工業風Loft公寓",
]

# 中文相機語言
CAMERA_MOVES_ZH = [
    "緩慢推鏡",
    "柔和跟蹤鏡頭",
    "手持跟拍",
    "靜態廣角",
    "低角度特寫",
    "俯瞰鳥瞰",
    "平滑升降鏡頭",
    "慢慢推近",
    "平視中景",
    "對焦拉換",
]

# ── Prompt Templates ─────────────────────────────────────────

PROMPTS: dict[str, list[str]] = {

    "litter_box": [
        # 貓咪進出，設備自動清潔
        "A {cat_breed} cat walking confidently into a {color} {product_name}, "
        "the {key_feature} activates silently after it leaves, "
        "{setting}, soft ambient morning light, cinematic 9:16 vertical",

        # 特寫：清潔機制
        "Extreme close-up of a {size} {color} {product_name}: {key_feature} "
        "running a full clean cycle in under 30 seconds — no scooping, no odor, "
        "fresh litter ready, {setting} background, 9:16 vertical",

        # 分割畫面：主人放鬆 vs 設備自動工作
        "Split-screen: a {cat_breed} cat owner relaxing on the sofa checking phone, "
        "while the {color} {product_name} in the {setting} quietly does {key_feature} "
        "— zero human effort, 9:16 vertical short",

        # 貓咪第一次探索
        "A curious {cat_breed} cat cautiously sniffing and circling a brand-new "
        "{color} {product_name} for the first time, then stepping in confidently, "
        "{key_feature} impresses even the cat, {setting}, warm lighting, 9:16",

        # 縮時：全天三次自動清潔
        "Time-lapse in a {setting}: a {cat_breed} cat uses the {size} {product_name} "
        "three times — each time {key_feature} resets it to perfectly clean, "
        "seamless automated routine, 9:16 vertical",
    ],

    "smart_feeder": [
        # 準時出糧，貓咪衝過來
        "A {cat_breed} cat perking its ears up and sprinting across the {setting} "
        "the moment the {color} {product_name} dispenses a meal — {key_feature} "
        "working perfectly on schedule, golden hour light, 9:16 vertical",

        # 主人遠端控制
        "Phone screen shows the {product_name} app — owner taps 'feed now' from "
        "the office, back home in the {setting} the {color} feeder dispenses kibble, "
        "a {cat_breed} cat rushes in excitedly, {key_feature} in action, 9:16",

        # 特寫：出糧慢動作
        "Slow motion close-up: {key_feature} — kibble falling in a perfect arc from "
        "the {size} {color} {product_name} into the bowl, a {cat_breed} cat's eyes "
        "tracking every piece, {setting}, soft studio lighting, 9:16 vertical",

        # 貓咪等待→進食
        "A patient {cat_breed} cat sitting upright in front of the {color} "
        "{product_name}, tail wrapped around paws — the timer hits zero, "
        "{key_feature} kicks in, the cat dives in immediately, {setting}, 9:16",

        # 雙貓共食
        "Two cats in a {setting} — a {cat_breed} and a ginger tabby — both eating "
        "simultaneously from the {size} {product_name}, {key_feature} ensuring "
        "each gets their portion, no fighting, warm lighting, 9:16 vertical",
    ],

    "water_fountain": [
        # 優雅飲水
        "A graceful {cat_breed} cat drinking from a {color} {product_name}, "
        "the {key_feature} creating a gentle flow that the cat clearly prefers, "
        "{setting}, soft bokeh background, 9:16 vertical",

        # 慢動作水流
        "Extreme slow motion: water flowing from the {size} {color} {product_name}, "
        "{key_feature} visible — a {cat_breed} cat's tongue delicately lapping each "
        "stream, droplets sparkling in {setting} light, 9:16 vertical cinematic",

        # 對比：靜止水碗 vs 流動噴泉
        "Side-by-side: a {cat_breed} cat sniffing and ignoring a plain water bowl, "
        "then rushing to drink enthusiastically from the {color} {product_name} — "
        "{key_feature} makes all the difference, {setting}, 9:16",

        # 清潔機制特寫
        "Close-up of the {product_name}'s {key_feature} working silently, "
        "crystal-clear filtered water flowing into the {color} bowl, "
        "a {cat_breed} cat approaching with interest, {setting}, 9:16 vertical",

        # 主人看著貓喝水
        "A cat owner smiling as their {cat_breed} cat drinks enthusiastically from "
        "the new {color} {size} {product_name}, {key_feature} clearly visible, "
        "peaceful {setting}, afternoon light, 9:16 vertical",
    ],

    "pet_camera": [
        # 主人遠端看貓
        "Smartphone screen showing a live view of a {cat_breed} cat playing in the "
        "{setting} via the {product_name} — {key_feature} tracks every move, "
        "the owner watching from afar with a big smile, 9:16 vertical",

        # 相機跟蹤貓咪
        "The {color} {product_name} smoothly rotates 360 degrees following a "
        "{cat_breed} cat running and leaping around the {setting}, "
        "{key_feature} perfectly framing every moment, 9:16 vertical short",

        # 推送通知提醒
        "Phone notification pops up from the {product_name} app — owner taps it to "
        "reveal live footage of their {cat_breed} cat doing something adorable in the "
        "{setting}, {key_feature} captured the whole thing, 9:16",

        # 互動零食投射
        "A {cat_breed} cat in the {setting} looks up suddenly as the {color} "
        "{product_name} activates its {key_feature} — the cat jumps for the treat, "
        "caught in perfect slow motion, cinematic 9:16 vertical",

        # 夜視效果
        "Night-vision view from the {product_name}: a {cat_breed} cat prowling "
        "silently through the darkened {setting} — {key_feature} reveals every "
        "detail in eerie green clarity, atmospheric 9:16 vertical",
    ],

    "gps_tracker": [
        # 貓咪戴著追蹤器探索戶外
        "A {cat_breed} cat wearing a {color} {product_name} on its collar, "
        "confidently exploring a sunlit garden — phone app shows {key_feature} "
        "updating in real-time, owner relaxed at home, 9:16 vertical",

        # App 地圖追蹤
        "Close-up of phone screen showing the {product_name} app map — a blinking "
        "dot moves as the {cat_breed} cat roams the neighborhood, {key_feature} "
        "pinpointing exact location, owner relaxed, {setting}, 9:16",

        # 逃跑警報
        "Phone buzzes with an escape alert from the {product_name} — the owner "
        "opens the app, {key_feature} shows the {cat_breed} cat three streets away, "
        "they walk straight to it and carry the cat home, 9:16 vertical",

        # 特寫：追蹤器體積小
        "Extreme close-up of the {size} {color} {product_name} clipped onto a "
        "{cat_breed} cat's collar — barely noticeable, but {key_feature} "
        "works 24/7, the cat walks away unbothered, bright outdoor light, 9:16",

        # 健康數據
        "The {product_name} app dashboard on phone showing a {cat_breed} cat's "
        "daily activity — {key_feature} displayed in clean graphs, {setting} "
        "visible through window, owner reviewing the data, 9:16 vertical",
    ],

    "cat_toy": [
        # 貓咪全力追玩具
        "A {cat_breed} cat exploding into a full sprint across the {setting}, "
        "chasing the {color} {product_name} — {key_feature} keeping it one step "
        "ahead, pure hunting instinct on display, slow motion, 9:16 vertical",

        # 自動玩具無人監督
        "The {product_name} running on its own in the {setting} while a {cat_breed} "
        "cat circles it obsessively — {key_feature} surprising the cat every time, "
        "owner watching from the couch laughing, 9:16 vertical",

        # 特寫：玩具機制
        "Slow motion close-up of the {size} {color} {product_name} activating: "
        "{key_feature} catches a {cat_breed} cat completely off-guard, "
        "the cat's pupils dilate instantly, {setting}, cinematic 9:16",

        # 貓咪跳躍接住玩具
        "A {cat_breed} cat leaps from the floor in perfect arc, front paws extending "
        "to catch the {color} {product_name} — {key_feature} made it irresistible, "
        "{setting}, dramatic slow motion, 9:16 vertical short",

        # 前後對比：懶貓 vs 玩耍的貓
        "Before-after split: {cat_breed} cat lying motionless on couch — then the "
        "{product_name} activates its {key_feature}, and the same cat transforms into "
        "a sprinting hunter, {setting}, 9:16 vertical",
    ],

    "grooming": [
        # 貓咪享受梳理
        "A {cat_breed} cat leaning blissfully into a grooming session with the "
        "{color} {product_name}, eyes half-closed in pure satisfaction — "
        "{key_feature} working through the coat effortlessly, {setting}, 9:16",

        # 特寫：去毛效果
        "Slow motion close-up: {key_feature} — the {size} {color} {product_name} "
        "gliding through a {cat_breed} cat's fur, removing a cloud of loose hair "
        "in a single smooth stroke, {setting} background, cinematic 9:16 vertical",

        # 梳毛前後對比
        "Split screen: before and after the {product_name} — a {cat_breed} cat's "
        "coat transforms from fluffy chaos to sleek perfection, {key_feature} "
        "making the difference, {setting}, soft studio light, 9:16",

        # 貓咪主動靠近
        "A {cat_breed} cat in the {setting} walking up to its owner and rubbing "
        "against the {color} {product_name} — {key_feature} is so gentle the cat "
        "initiates grooming itself, warm cozy light, 9:16 vertical",

        # 清理工具特寫
        "Close-up of the {product_name}: {key_feature} — a satisfying demonstration "
        "of the tool working perfectly, then a {cat_breed} cat in the {setting} "
        "looking immaculate and calm, 9:16 vertical",
    ],

    "cat_bed": [
        # 貓咪第一次試躺
        "A {cat_breed} cat approaching the new {color} {product_name} cautiously, "
        "sniffing every inch, then slowly stepping in and curling up perfectly — "
        "{key_feature} wins the cat over immediately, {setting}, 9:16 vertical",

        # 熟睡特寫
        "Extreme close-up of a {cat_breed} cat sleeping deeply in the {size} "
        "{color} {product_name} — {key_feature} creating the perfect sleep environment, "
        "soft warm light, the cat's whiskers twitching gently, 9:16",

        # 前後對比：睡沙發 vs 睡新床
        "Split-screen: {cat_breed} cat stubbornly sleeping on the owner's laptop — "
        "then the {color} {product_name} arrives, {key_feature} tested, and now the "
        "cat hasn't left the bed in days, {setting}, 9:16 vertical",

        # 貓咪把整個身體捲進去
        "A fluffy {cat_breed} cat methodically kneading the {color} {product_name}, "
        "then curling into a perfect spiral — {key_feature} holding that cozy form, "
        "{setting}, golden hour light, cinematic 9:16 vertical short",

        # 主人與貓咪共享溫馨時刻
        "A {cat_breed} cat peacefully napping in the {size} {color} {product_name} "
        "while its owner reads nearby in the {setting} — {key_feature} means the cat "
        "finally stopped stealing the bed, warm domestic scene, 9:16",
    ],

    # 通用生活風格 — 適合任何產品
    "lifestyle": [
        "Montage of a {cat_breed} cat living its best automated life in a {setting}: "
        "{product_name} running perfectly, {key_feature} handling everything — "
        "no human required, cozy morning light, 9:16 vertical",

        "A {cat_breed} cat sitting regally surrounded by glowing smart devices in the "
        "{setting}, the {color} {product_name} working silently — clearly the cat is "
        "the one in charge, cinematic 9:16 vertical short",

        "Timelapse of a full smart-cat day in a {setting}: morning {product_name} "
        "running {key_feature}, a {cat_breed} cat checking each gadget approvingly, "
        "evening cuddle — perfectly automated life, 9:16",
    ],
}


# ── Core functions ───────────────────────────────────────────

def fill_prompt(template: str, product: dict) -> str:
    """
    用產品資料填充英文 prompt template 的變數。
    所有變數都有安全 fallback，不會因缺欄位而報錯。
    額外注入：{camera_move}（隨機）、{director_style}（隨機）
    """
    return template.format(
        product_name   = product.get("name", "smart cat device"),
        key_feature    = product.get("key_feature", "innovative automated feature"),
        color          = product.get("color", "sleek white"),
        size           = product.get("size", "compact"),
        cat_breed      = random.choice(CAT_BREEDS),
        setting        = random.choice(SETTINGS),
        camera_move    = random.choice(CAMERA_MOVES),
        director_style = random.choice(DIRECTOR_STYLES),
    )


def fill_prompt_zh(template: str, product: dict) -> str:
    """
    填充中文 prompt template（專給 HuggingFace Wan2.x 使用）。
    研究依據：Wan 2.6/2.7 中文 prompt 效果顯著優於英文。
    """
    return template.format(
        product_name   = product.get("name", "智慧寵物裝置"),
        key_feature_zh = product.get("key_feature", "全自動智慧功能"),
        color          = product.get("color", "白色"),
        size_zh        = product.get("size", "精巧"),
        cat_breed_zh   = random.choice(CAT_BREEDS_ZH),
        setting_zh     = random.choice(SETTINGS_ZH),
        camera_move_zh = random.choice(CAMERA_MOVES_ZH),
    )


def get_prompt_for_product(product: dict) -> str:
    """
    根據產品類別隨機選一個英文 template，填入產品資料後回傳完整 prompt。
    這是 main_smartcat.py → Veo3 / Kling / Hailuo / EaseMate 的主要呼叫入口。
    """
    category  = product.get("category", "lifestyle")
    templates = PROMPTS.get(category, PROMPTS["lifestyle"])
    template  = random.choice(templates)
    return fill_prompt(template, product)


def get_prompt_for_product_hf(product: dict) -> str:
    """
    回傳中文版 prompt — 專用於 HuggingFace Wan2.1 後端。
    若該類別無中文模板，自動 fallback 至英文版。
    """
    category     = product.get("category", "lifestyle")
    zh_templates = PROMPTS_ZH.get(category, PROMPTS_ZH.get("lifestyle", []))
    if zh_templates:
        return fill_prompt_zh(random.choice(zh_templates), product)
    # fallback：英文版
    return get_prompt_for_product(product)


def get_prompts_for_product(product: dict, count: int = 3) -> list[str]:
    """
    一次生成 count 個不同的英文 prompt（同產品，不同貓咪品種 + 場景 + 相機動作）。
    用於同一天生多支影片，確保每支風格不同。
    """
    category  = product.get("category", "lifestyle")
    templates = PROMPTS.get(category, PROMPTS["lifestyle"])

    # 確保拿到 count 個不同 template（若 template 不夠就允許重複但隨機變數不同）
    if count <= len(templates):
        selected_templates = random.sample(templates, count)
    else:
        selected_templates = random.choices(templates, k=count)

    return [fill_prompt(t, product) for t in selected_templates]


# 每日排程輪換（相容舊介面）
def get_daily_prompts(count: int = 3) -> list:
    """根據今天日期選出今日要用的提示詞（不帶產品資料，舊介面相容）"""
    all_prompts = []
    for category, templates in PROMPTS.items():
        for t in templates:
            all_prompts.append({"category": category, "prompt": t})

    day_index = datetime.datetime.now().timetuple().tm_yday
    start = (day_index * count) % len(all_prompts)
    return [all_prompts[(start + i) % len(all_prompts)] for i in range(count)]


if __name__ == "__main__":
    from affiliate_products import get_product_from_weekly

    print("=== 動態 Prompt 測試 ===\n")
    for i in range(3):
        product = get_product_from_weekly(day_offset=i)
        prompt  = get_prompt_for_product(product)
        print(f"[{i+1}] 產品: {product['name'][:50]}")
        print(f"    類別: {product.get('category','?')}")
        print(f"    key_feature: {product.get('key_feature','?')[:50]}")
        print(f"    Prompt:\n    {prompt}\n")
