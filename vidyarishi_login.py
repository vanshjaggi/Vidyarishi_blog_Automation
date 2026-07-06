import os
import platform
import re
import tempfile
import time
import json
import sys
from datetime import datetime

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    InvalidSessionIdException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait


LOGIN_URL = "https://blog.vidyarishi.com/login"
WAIT_SECONDS = 25
FIELD_SETTLE_SECONDS = float(os.getenv("FIELD_SETTLE_SECONDS", "0.35"))
PAGE_SETTLE_SECONDS = float(os.getenv("PAGE_SETTLE_SECONDS", "0.8"))
SUBMIT_SETTLE_SECONDS = float(os.getenv("SUBMIT_SETTLE_SECONDS", "1.0"))
PRINT_PAYLOAD_SUMMARY = os.getenv("PRINT_PAYLOAD_SUMMARY", "false").lower() in {"1", "true", "yes"}
MAX_BLOG_CONTENT_BYTES = 250_000
CONFIRMED_BLOGS_OUTPUT_PATH = os.path.abspath("confirmed_blogs.csv")
SKIPPED_BLOGS_OUTPUT_PATH = os.path.abspath("skipped_blogs.csv")
FAILED_BLOGS_OUTPUT_PATH = os.path.abspath("failed_blogs.csv")
RUN_HISTORY_PATH = os.path.abspath("run_history.jsonl")
SOURCE_PLACE = "Sherpur"
BLOG_CATEGORY = "SEO"
BLOG_TAG = "Seo"
META_KEYWORDS = "mba, online-mba, online-degree, online-courses"
BLOG_TITLE_LOCATORS = [
    (By.NAME, "title"),
    (By.NAME, "blogTitle"),
    (By.ID, "title"),
    (By.ID, "blogTitle"),
    (By.CSS_SELECTOR, "input[name*='title' i]"),
    (By.CSS_SELECTOR, "input[id*='title' i]"),
    (
        By.XPATH,
        "//input[contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'title')]",
    ),
]
BLOG_CONTENT_PATH = os.path.abspath(
    "hello_with_images.html" if os.path.exists("hello_with_images.html") else "hello.txt"
)
THUMBNAIL_PATH = os.path.abspath(os.path.join("public", "thumbnail mba.jpg"))
PAUSE_BEFORE_NEXT_SUBMIT = False
IN_GUI_MODE = False


class DuplicateBlogError(RuntimeError):
    pass


def env_value(*names):
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def parse_places():
    raw_places = env_value("PLACES", "BLOG_PLACES", "PLACE")
    if not raw_places:
        return [SOURCE_PLACE]

    places = [place.strip() for place in re.split(r"[,;\n|]+", raw_places)]
    return [place for place in places if place]


def blog_title(place):
    return f"Online MBA in {place}"


def title_with_suffix(place, suffix=None):
    title = blog_title(place)
    return f"{title} - {suffix}" if suffix else title


def roman_numeral(number):
    values = [
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ]
    result = []
    for value, numeral in values:
        while number >= value:
            result.append(numeral)
            number -= value
    return "".join(result)


def blog_slug(place, suffix=None):
    slug = title_with_suffix(place, suffix).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def blog_path(place, suffix=None):
    return f"/{blog_slug(place, suffix)}"


def meta_title(place):
    full_title = f"Online MBA in {place} | Flexible MBA Programs Online"
    if len(full_title) <= 60:
        return full_title

    shorter_title = f"Online MBA in {place} | MBA Programs Online"
    if len(shorter_title) <= 60:
        return shorter_title

    return f"Online MBA in {place}"


def meta_description(place):
    description = (
        f"Explore Online MBA in {place} with flexible learning, career growth, top "
        "specializations, salary scope, and trusted programs by Vidyarishi India."
    )
    if len(description) > 160:
        description = description.replace(", and trusted programs by Vidyarishi India", "")
        description = description.replace(" by Vidyarishi India", "")
    return description


def content_for_place(template_content, place):
    return template_content.replace(SOURCE_PLACE, place)


def strip_embedded_images(content):
    return re.sub(
        r"<img\b[^>]*\bsrc=[\"']data:image/[^\"']+[\"'][^>]*>",
        "",
        content,
        flags=re.IGNORECASE,
    )


def prepare_blog_content(template_content):
    original_size = len(template_content.encode("utf-8"))
    if original_size <= MAX_BLOG_CONTENT_BYTES:
        print(f"Blog content size is OK: {original_size} bytes.")
        return template_content

    cleaned_content = strip_embedded_images(template_content)
    cleaned_size = len(cleaned_content.encode("utf-8"))

    fallback_path = os.path.abspath("hello.txt")
    if cleaned_size <= MAX_BLOG_CONTENT_BYTES:
        print(
            "Blog content was too large with images "
            f"({original_size} bytes), so embedded images were removed "
            f"({cleaned_size} bytes)."
        )
        return cleaned_content

    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as fallback_file:
            fallback_content = fallback_file.read()
        fallback_size = len(fallback_content.encode("utf-8"))
        if fallback_size <= MAX_BLOG_CONTENT_BYTES:
            print(
                "Blog content is still too large after image removal "
                f"({cleaned_size} bytes). Using hello.txt instead ({fallback_size} bytes)."
            )
            return fallback_content

    raise RuntimeError(
        "Blog content is too large for the backend request "
        f"({original_size} bytes with images, {cleaned_size} bytes without images). "
        "Compress images further or reduce the content size."
    )


def format_duration(seconds):
    seconds = int(round(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def append_run_history(record):
    with open(RUN_HISTORY_PATH, "a", encoding="utf-8") as history_file:
        history_file.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_browser():
    chrome_options = Options()
    profile_path = tempfile.mkdtemp(prefix="vidyarishi-chrome-")

    should_detach = os.getenv("VIDYARISHI_DETACH", "true").lower() in {"1", "true", "yes"}

    if platform.system() == "Windows" and should_detach:
        chrome_options.add_experimental_option("detach", True)
    elif platform.system() == "Darwin":
        chrome_options.binary_location = (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        )

    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--remote-allow-origins=*")
    chrome_options.add_argument(f"--user-data-dir={profile_path}")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(options=chrome_options)


def find_first(wait, locators, label, must_be_clickable=False):
    def locate(driver):
        for by, selector in locators:
            for element in driver.find_elements(by, selector):
                if not element.is_displayed():
                    continue
                if must_be_clickable and not element.is_enabled():
                    continue
                return element
        return False

    try:
        return wait.until(locate)
    except TimeoutException as error:
        raise TimeoutException(f"Could not find {label}") from error


def print_page_debug(browser, context="an expected element"):
    print(f"\nCould not find {context}.")
    print(f"Page title: {browser.title}")
    print(f"Current URL: {browser.current_url}")
    print("\nVisible inputs:")
    inputs = browser.find_elements(By.CSS_SELECTOR, "input")
    for index, element in enumerate(inputs, start=1):
        if element.is_displayed():
            print(
                f"{index}. type={element.get_attribute('type')!r} "
                f"name={element.get_attribute('name')!r} "
                f"id={element.get_attribute('id')!r} "
                f"placeholder={element.get_attribute('placeholder')!r}"
            )

    print("\nVisible buttons:")
    buttons = browser.find_elements(By.CSS_SELECTOR, "button, input[type='button'], input[type='submit']")
    for index, element in enumerate(buttons, start=1):
        if element.is_displayed():
            text = element.text or element.get_attribute("value")
            print(
                f"{index}. text={text!r} "
                f"name={element.get_attribute('name')!r} "
                f"id={element.get_attribute('id')!r}"
            )

    print("\nVisible links:")
    links = browser.find_elements(By.CSS_SELECTOR, "a")
    for index, element in enumerate(links, start=1):
        if element.is_displayed():
            print(
                f"{index}. text={element.text!r} "
                f"href={element.get_attribute('href')!r}"
            )

    body_text = browser.execute_script(
        "return document.body ? document.body.innerText.slice(0, 2000) : '';"
    )
    print("\nPage text preview:")
    print(body_text)


def click_text(wait, text, label=None):
    lower_text = text.lower()
    element_label = label or text
    xpath = (
        "//*[self::a or self::button or @role='button' or self::div or self::span]"
        f"[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        f"'abcdefghijklmnopqrstuvwxyz'), {lower_text!r})]"
    )
    element = find_first(wait, [(By.XPATH, xpath)], element_label, must_be_clickable=True)
    element.click()
    return element


def click_element(browser, element):
    browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(0.2)

    try:
        element.click()
        return
    except WebDriverException:
        pass

    browser.execute_script(
        """
        const el = arguments[0];
        el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
        el.click();
        """,
        element,
    )


def click_text_anywhere(wait, browser, texts, label):
    lowered_texts = [text.lower() for text in texts]

    def locate(driver):
        driver.switch_to.default_content()

        for scroll_y in (0, 350, 800, 1300, 1900, 2600):
            driver.execute_script("window.scrollTo(0, arguments[0]);", scroll_y)
            time.sleep(0.2)

            for lower_text in lowered_texts:
                xpath = (
                    "//*[not(self::script) and not(self::style)]"
                    f"[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                    f"'abcdefghijklmnopqrstuvwxyz'), {lower_text!r})]"
                )
                for element in driver.find_elements(By.XPATH, xpath):
                    if not element.is_displayed():
                        continue

                    clickable = driver.execute_script(
                        """
                        const el = arguments[0];
                        return el.closest('a, button, [role="button"], [onclick], .card, .cursor-pointer') || el;
                        """,
                        element,
                    )
                    if clickable and clickable.is_displayed():
                        return clickable

        return False

    element = wait.until(locate)
    browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    browser.execute_script("arguments[0].click();", element)
    return element


def request_otp(wait, browser, password_field):
    otp_button_locators = [
        (By.ID, "getOtp"),
        (By.ID, "get_otp"),
        (By.ID, "sendOtp"),
        (By.ID, "send_otp"),
        (By.NAME, "getOtp"),
        (By.NAME, "sendOtp"),
        (
            By.XPATH,
            "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'otp')]",
        ),
        (
            By.XPATH,
            "//input[@type='button' or @type='submit'][contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'otp')]",
        ),
        (
            By.XPATH,
            "//*[self::button or self::a or @role='button'][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'send')]",
        ),
    ]

    try:
        otp_button = find_first(
            wait,
            otp_button_locators,
            "Get/Send OTP button",
            must_be_clickable=True,
        )
        print(
            "Clicking OTP button: "
            f"text={(otp_button.text or otp_button.get_attribute('value') or '').strip()!r}"
        )
        click_element(browser, otp_button)
        return
    except TimeoutException:
        print_page_debug(browser, "Get/Send OTP button")
        raise
    except WebDriverException:
        print("Normal OTP button click failed. Trying Enter key fallback...")
        password_field.send_keys(Keys.ENTER)


def page_has_blog_form(browser):
    title_fields = browser.find_elements(By.CSS_SELECTOR, "input[name*='title' i], input[id*='title' i]")
    file_fields = browser.find_elements(By.CSS_SELECTOR, "input[type='file']")
    editors = browser.find_elements(By.CSS_SELECTOR, "textarea, [contenteditable='true'], .ql-editor, iframe")
    return bool(title_fields or (file_fields and editors))


def open_create_blog_page(wait, browser):
    if page_has_blog_form(browser):
        return

    def click_exact_visible_create(driver):
        driver.switch_to.default_content()
        driver.execute_script("window.scrollTo(0, 0);")
        candidates = driver.find_elements(By.CSS_SELECTOR, "a, button, [role='button']")

        for element in candidates:
            try:
                if not element.is_displayed() or not element.is_enabled():
                    continue

                text = (element.text or element.get_attribute("innerText") or "").strip()
                aria_label = (element.get_attribute("aria-label") or "").strip()
                href = element.get_attribute("href") or ""
                combined = f"{text} {aria_label}".lower()

                if "create blog" in combined or "create-blog" in href.lower():
                    return element
            except StaleElementReferenceException:
                continue

        return False

    print("Trying exact Create Blog click...")
    try:
        create_button = WebDriverWait(browser, 4).until(click_exact_visible_create)
        browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", create_button)
        browser.execute_script("arguments[0].click();", create_button)
        time.sleep(PAGE_SETTLE_SECONDS)
        if page_has_blog_form(browser):
            return
    except (StaleElementReferenceException, TimeoutException):
        pass

    print("Trying dashboard text click...")
    try:
        click_text_anywhere(
            WebDriverWait(browser, 6),
            browser,
            ["Create Blog", "Create Blogs", "Add Blog", "Write Blog"],
            "Create Blog quick action",
        )
        time.sleep(PAGE_SETTLE_SECONDS)
        if page_has_blog_form(browser):
            return
    except TimeoutException:
        pass

    print("Trying likely Create Blog URLs...")
    route_candidates = [
        "https://blog.vidyarishi.com/author/create",
        "https://blog.vidyarishi.com/author/create-blog",
        "https://blog.vidyarishi.com/author/blog/create",
        "https://blog.vidyarishi.com/author/blogs/create",
        "https://blog.vidyarishi.com/author/create/blog",
    ]

    for url in route_candidates:
        browser.get(url)
        time.sleep(PAGE_SETTLE_SECONDS)
        if page_has_blog_form(browser):
            print(f"Opened Create Blog page directly: {url}")
            return

    print_page_debug(browser, "Create Blog page")
    raise TimeoutException("Could not open Create Blog page")


def set_field(wait, browser, label, value, locators):
    field = find_first(wait, locators, label)
    browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", field)
    field.click()
    field.send_keys(Keys.CONTROL, "a")
    field.send_keys(value)
    field.send_keys(Keys.TAB)
    time.sleep(FIELD_SETTLE_SECONDS)
    return field


def set_labeled_field(wait, browser, label_text, value, extra_locators=None):
    lower_label = label_text.lower()
    locators = extra_locators or []
    locators.extend(
        [
            (
                By.XPATH,
                f"//*[self::label or self::span or self::div or self::p]"
                f"[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                f"'abcdefghijklmnopqrstuvwxyz'), {lower_label!r})]"
                "/following::*[self::input or self::textarea][1]",
            ),
            (
                By.XPATH,
                f"//input[contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                f"'abcdefghijklmnopqrstuvwxyz'), {lower_label!r})]",
            ),
            (
                By.XPATH,
                f"//textarea[contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                f"'abcdefghijklmnopqrstuvwxyz'), {lower_label!r})]",
            ),
        ]
    )

    try:
        return set_field(wait, browser, label_text, value, locators)
    except TimeoutException:
        print_page_debug(browser, label_text)
        raise


def set_blog_title(wait, browser, title):
    set_field(
        wait,
        browser,
        "blog title field",
        title,
        BLOG_TITLE_LOCATORS,
    )


def meta_title_field_exists(browser):
    selectors = [
        "input[name='metaTitle']",
        "input[name='meta_title']",
        "input[id='metaTitle']",
        "input[id='meta_title']",
        "input[name*='meta'][name*='title' i]",
        "input[id*='meta'][id*='title' i]",
    ]
    for selector in selectors:
        for element in browser.find_elements(By.CSS_SELECTOR, selector):
            if element.is_displayed():
                return True
    return False


def open_seo_settings(wait, browser):
    if meta_title_field_exists(browser):
        return

    print("Opening SEO Settings tab...")

    exact_tab_locators = [
        (
            By.XPATH,
            "//button[normalize-space(.)='SEO Settings']",
        ),
        (
            By.XPATH,
            "//*[self::button or self::a or @role='tab' or @role='button']"
            "[normalize-space(.)='SEO Settings']",
        ),
        (
            By.XPATH,
            "//*[self::button or self::a or @role='tab' or @role='button']"
            "[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
            "'abcdefghijklmnopqrstuvwxyz'), 'seo settings')]",
        ),
    ]

    try:
        seo_tab = find_first(wait, exact_tab_locators, "SEO Settings tab", must_be_clickable=True)
        click_element(browser, seo_tab)
        time.sleep(PAGE_SETTLE_SECONDS)
        if meta_title_field_exists(browser):
            return
    except TimeoutException:
        pass

    def locate_and_click(driver):
        driver.switch_to.default_content()

        for scroll_y in (0, 150, 600, 1200, 1800, 2400, 3200, 4200, 5200):
            driver.execute_script("window.scrollTo(0, arguments[0]);", scroll_y)
            time.sleep(0.2)

            elements = driver.find_elements(
                By.XPATH,
                "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'seo settings') or "
                "normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))='seo']",
            )

            for element in elements:
                if not element.is_displayed():
                    continue

                clickable = driver.execute_script(
                    """
                    const el = arguments[0];
                    return el.closest(
                        'button, a, [role="tab"], [role="button"], .nav-link, .tab, '
                        + '.accordion-button, .accordion-header, '
                        + '.card-header, .collapse-title, [data-bs-toggle], [data-toggle], '
                        + '[onclick], summary, h1, h2, h3, h4, h5, h6'
                    ) || el;
                    """,
                    element,
                )

                if clickable and clickable.is_displayed():
                    return clickable

        return False

    try:
        seo_toggle = wait.until(locate_and_click)
        click_element(browser, seo_toggle)
        time.sleep(PAGE_SETTLE_SECONDS)
    except TimeoutException:
        pass

    if meta_title_field_exists(browser):
        return

    browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(PAGE_SETTLE_SECONDS)


def open_write_blog(wait, browser):
    print("Opening Write Blog tab...")
    write_tab_locators = [
        (By.XPATH, "//button[normalize-space(.)='Write Blog']"),
        (
            By.XPATH,
            "//*[self::button or self::a or @role='tab' or @role='button']"
            "[normalize-space(.)='Write Blog']",
        ),
        (
            By.XPATH,
            "//*[self::button or self::a or @role='tab' or @role='button']"
            "[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
            "'abcdefghijklmnopqrstuvwxyz'), 'write blog')]",
        ),
    ]
    write_tab = find_first(wait, write_tab_locators, "Write Blog tab", must_be_clickable=True)
    click_element(browser, write_tab)
    time.sleep(PAGE_SETTLE_SECONDS)


def fill_seo_settings(wait, browser, place):
    print("Filling SEO settings...")
    open_seo_settings(wait, browser)

    set_labeled_field(
        wait,
        browser,
        "Meta Title",
        meta_title(place),
        [
            (By.NAME, "metaTitle"),
            (By.NAME, "meta_title"),
            (By.ID, "metaTitle"),
            (By.ID, "meta_title"),
            (By.CSS_SELECTOR, "input[name*='meta'][name*='title' i]"),
            (By.CSS_SELECTOR, "input[id*='meta'][id*='title' i]"),
        ],
    )

    set_labeled_field(
        wait,
        browser,
        "Meta Description",
        meta_description(place),
        [
            (By.NAME, "metaDescription"),
            (By.NAME, "meta_description"),
            (By.ID, "metaDescription"),
            (By.ID, "meta_description"),
            (By.CSS_SELECTOR, "textarea[name*='meta'][name*='description' i]"),
            (By.CSS_SELECTOR, "textarea[id*='meta'][id*='description' i]"),
            (By.CSS_SELECTOR, "input[name*='meta'][name*='description' i]"),
            (By.CSS_SELECTOR, "input[id*='meta'][id*='description' i]"),
        ],
    )

    set_labeled_field(
        wait,
        browser,
        "Meta Keywords",
        META_KEYWORDS,
        [
            (By.NAME, "metaKeywords"),
            (By.NAME, "meta_keywords"),
            (By.ID, "metaKeywords"),
            (By.ID, "meta_keywords"),
            (By.CSS_SELECTOR, "textarea[name*='keyword' i]"),
            (By.CSS_SELECTOR, "textarea[id*='keyword' i]"),
            (By.CSS_SELECTOR, "input[name*='keyword' i]"),
            (By.CSS_SELECTOR, "input[id*='keyword' i]"),
        ],
    )


def settle_form_before_submit(browser):
    print("Letting editor/form state settle before submit...")
    browser.switch_to.default_content()
    browser.execute_script(
        """
        if (window.Jodit && window.Jodit.instances) {
            Object.values(window.Jodit.instances).forEach((instance) => {
                if (typeof instance.synchronizeValues === 'function') instance.synchronizeValues();
                if (typeof instance.e?.fire === 'function') instance.e.fire('change');
                if (instance.editor) instance.editor.blur();
                if (instance.element) {
                    instance.element.dispatchEvent(new Event('input', { bubbles: true }));
                    instance.element.dispatchEvent(new Event('change', { bubbles: true }));
                    instance.element.blur();
                }
            });
        }

        if (window.tinymce && window.tinymce.editors) {
            window.tinymce.editors.forEach((editor) => {
                editor.save();
                editor.fire('input');
                editor.fire('change');
                editor.fire('blur');
            });
        }

        if (window.CKEDITOR && window.CKEDITOR.instances) {
            Object.values(window.CKEDITOR.instances).forEach((editor) => {
                editor.updateElement();
                editor.fire('change');
                editor.fire('blur');
            });
        }

        document.querySelectorAll('input, textarea, [contenteditable="true"], .ql-editor')
            .forEach((node) => {
                node.dispatchEvent(new Event('input', { bubbles: true }));
                node.dispatchEvent(new Event('change', { bubbles: true }));
                node.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
            });

        if (document.activeElement && document.activeElement.blur) {
            document.activeElement.blur();
        }
        """
    )
    try:
        browser.find_element(By.TAG_NAME, "body").click()
    except WebDriverException:
        browser.execute_script("document.body && document.body.click();")
    time.sleep(SUBMIT_SETTLE_SECONDS)


def get_submit_errors(browser):
    return browser.execute_script(
        """
        const selectors = [
            '.error', '.invalid', '.invalid-feedback', '.is-invalid',
            '.toast', '.Toastify__toast', '.alert', '.swal2-popup',
            '[role="alert"]', '[aria-invalid="true"]'
        ];
        const seen = new Set();
        const messages = [];

        document.querySelectorAll(selectors.join(',')).forEach((node) => {
            const text = (node.innerText || node.textContent || '').trim();
            if (text && !seen.has(text)) {
                seen.add(text);
                messages.push(text);
            }
        });

        document.querySelectorAll('input:invalid, textarea:invalid, select:invalid').forEach((node) => {
            const label = node.name || node.id || node.placeholder || node.getAttribute('aria-label') || node.tagName;
            const text = `${label}: ${node.validationMessage || 'invalid value'}`;
            if (!seen.has(text)) {
                seen.add(text);
                messages.push(text);
            }
        });

        return messages;
        """
    )


def has_submit_success_message(browser):
    body_text = browser.execute_script(
        "return document.body ? document.body.innerText.toLowerCase() : '';"
    )
    return any(
        phrase in body_text
        for phrase in (
            "blog created successfully",
            "submitted for review",
            "blog submitted",
            "successfully submitted",
        )
    )


def print_submit_errors(browser):
    messages = get_submit_errors(browser)

    if messages:
        print("\nVisible submit errors:")
        for message in messages:
            print(f"ERROR: {message}")
    else:
        print("\nNo visible submit error text was found.")


def clear_recent_network_logs(browser):
    try:
        browser.get_log("performance")
    except (ValueError, WebDriverException):
        pass


def clear_submit_messages(browser):
    browser.execute_script(
        """
        const selectors = ['.toast', '.Toastify__toast', '.alert', '.swal2-container'];
        document.querySelectorAll(selectors.join(',')).forEach((node) => node.remove());
        """
    )


def recent_blog_api_failures(browser):
    try:
        logs = browser.get_log("performance")
    except (ValueError, WebDriverException) as error:
        return [{"status": 0, "status_text": "Network log unavailable", "url": "", "body": str(error)}]

    failures = []
    for entry in logs:
        try:
            message = json.loads(entry["message"])["message"]
        except (KeyError, TypeError, json.JSONDecodeError):
            continue

        if message.get("method") != "Network.responseReceived":
            continue

        params = message.get("params", {})
        response = params.get("response", {})
        url = response.get("url", "")
        status = int(response.get("status", 0) or 0)
        if "/blog" not in url or status < 400:
            continue

        failure = {
            "request_id": params.get("requestId"),
            "url": url,
            "status": status,
            "status_text": response.get("statusText", ""),
            "body": "",
        }
        request_id = failure.get("request_id")
        if request_id:
            try:
                body = browser.execute_cdp_cmd(
                    "Network.getResponseBody",
                    {"requestId": request_id},
                )
                failure["body"] = (body.get("body") or "").strip()
            except WebDriverException:
                pass
        failures.append(failure)

    return failures


def latest_blog_api_error_message(browser):
    failures = recent_blog_api_failures(browser)
    for failure in reversed(failures):
        body = failure.get("body") or ""
        if not body:
            continue
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return body
        message = data.get("message") or body
        if isinstance(message, list):
            return "; ".join(str(item) for item in message)
        return str(message)
    return ""


def print_recent_blog_api_failures(browser):
    failures = recent_blog_api_failures(browser)

    if not failures:
        print("\nNo failed /blog API response was found in Chrome network logs.")
        return

    print("\nRecent failed blog API responses:")
    for failure in failures[-5:]:
        print(f"API ERROR: {failure['status']} {failure['status_text']} {failure['url']}")
        response_body = (failure.get("body") or "").strip()
        if response_body:
            print(f"API RESPONSE: {response_body[:1000]}")


def print_form_payload_summary(browser):
    summary = browser.execute_script(
        """
        const summary = [];
        const seen = new Set();

        function add(name, value, source) {
            if (!name || seen.has(`${source}:${name}`)) return;
            seen.add(`${source}:${name}`);
            const text = String(value || '');
            summary.push({
                name,
                source,
                length: text.length,
                sample: text.slice(0, 80),
            });
        }

        document.querySelectorAll('input, textarea, select').forEach((node) => {
            const name = node.name || node.id || node.placeholder || node.type || node.tagName;
            if (node.type === 'file') {
                add(name, Array.from(node.files || []).map((file) => file.name).join(', '), 'file');
            } else if (node.tagName === 'SELECT') {
                add(name, node.value || node.options[node.selectedIndex]?.text || '', 'select');
            } else {
                add(name, node.value || '', node.tagName.toLowerCase());
            }
        });

        if (window.Jodit && window.Jodit.instances) {
            Object.entries(window.Jodit.instances).forEach(([key, instance]) => {
                add(`jodit.${key}`, instance.value || instance.editor?.innerText || '', 'editor');
            });
        }

        document.querySelectorAll('.jodit-wysiwyg, [contenteditable="true"], .ql-editor').forEach((node, index) => {
            add(`editable.${index}`, node.innerText || node.innerHTML || '', 'editable');
        });

        return summary;
        """
    )

    print("\nForm payload summary before submit:")
    for item in summary:
        sample = item.get("sample", "").replace("\n", " ")
        print(
            f"{item.get('source')}: {item.get('name')} "
            f"length={item.get('length')} sample={sample!r}"
        )


def submit_for_review(wait, browser):
    print("Submitting blog for review...")
    before_url = browser.current_url
    settle_form_before_submit(browser)
    if PRINT_PAYLOAD_SUMMARY:
        print_form_payload_summary(browser)
    clear_recent_network_logs(browser)
    clear_submit_messages(browser)
    submit_button = find_first(
        wait,
        [
            (By.XPATH, "//button[normalize-space(.)='Submit For Review']"),
            (By.XPATH, "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'submit for review')]"),
            (By.XPATH, "//input[@type='submit' and contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'submit')]"),
        ],
        "Submit For Review button",
        must_be_clickable=True,
    )
    try:
        click_element(browser, submit_button)
    except StaleElementReferenceException:
        time.sleep(SUBMIT_SETTLE_SECONDS)
        if has_submit_success_message(browser):
            print("Submitted for review.")
            return
        raise

    time.sleep(SUBMIT_SETTLE_SECONDS)
    try:
        confirm_button = find_first(
            WebDriverWait(browser, 4),
            [
                (By.XPATH, "//button[normalize-space(.)='OK']"),
                (By.XPATH, "//button[normalize-space(.)='Yes']"),
                (By.XPATH, "//button[normalize-space(.)='Confirm']"),
            ],
            "submit confirmation button",
            must_be_clickable=True,
        )
        click_element(browser, confirm_button)
    except TimeoutException:
        pass

    time.sleep(SUBMIT_SETTLE_SECONDS)

    def submitted(driver):
        if has_submit_success_message(driver):
            return True

        current_url = driver.current_url
        if current_url != before_url and "/author/create" not in current_url:
            return True

        errors = get_submit_errors(driver)
        lower_errors = "\n".join(errors).lower()
        if "blog created successfully" in lower_errors:
            return True
        if errors:
            return "error"

        return False

    try:
        result = WebDriverWait(browser, 25).until(submitted)
        if result == "error":
            visible_errors = get_submit_errors(browser)
            print_submit_errors(browser)
            print_recent_blog_api_failures(browser)
            api_message = latest_blog_api_error_message(browser)
            combined_error = "\n".join(visible_errors + [api_message]).lower()
            if "same title and slug already exists" in combined_error:
                raise DuplicateBlogError(api_message or "\n".join(visible_errors))
            raise RuntimeError("Submit failed: the website showed an error.")
        print("Submitted for review.")
    except TimeoutException:
        print_submit_errors(browser)
        print_recent_blog_api_failures(browser)
        print_page_debug(browser, "successful Submit For Review result")
        raise RuntimeError("Submit For Review did not complete, stopping batch.")
    except StaleElementReferenceException:
        if has_submit_success_message(browser):
            print("Submitted for review.")
            return
        raise


def visible_field_value(browser, locators):
    for by, selector in locators:
        for element in browser.find_elements(by, selector):
            if element.is_displayed():
                return element.get_attribute("value") or element.text or ""
    return ""


def blog_content_contains_marker(browser):
    return browser.execute_script(
        """
        const marker = arguments[0];
        const pieces = [];

        if (window.Jodit && window.Jodit.instances) {
            Object.values(window.Jodit.instances).forEach((instance) => {
                pieces.push(instance.value || '');
                if (instance.editor) pieces.push(instance.editor.innerText || instance.editor.innerHTML || '');
                if (instance.element) pieces.push(instance.element.value || '');
            });
        }

        document.querySelectorAll(
            'textarea[name*="content" i], textarea[id*="content" i], textarea, '
            + '.jodit-wysiwyg, [contenteditable="true"], .ql-editor'
        ).forEach((node) => {
            pieces.push(node.value || node.innerText || node.innerHTML || '');
        });

        return pieces.some((piece) => piece.includes(marker));
        """,
        "The demand for flexible",
    )


def select_dropdown_value(wait, browser, label_text, option_text):
    lower_label = label_text.lower()
    lower_option = option_text.lower()

    selects = browser.find_elements(By.CSS_SELECTOR, "select")
    for select_element in selects:
        if not select_element.is_displayed():
            continue

        nearby_text = browser.execute_script(
            """
            const el = arguments[0];
            const parent = el.closest('label, .form-group, .mb-3, .field, div') || el.parentElement;
            return parent ? parent.innerText : '';
            """,
            select_element,
        )

        if lower_label in (nearby_text or "").lower():
            select = Select(select_element)
            for option in select.options:
                if option_text.lower() == option.text.strip().lower():
                    select.select_by_visible_text(option.text)
                    time.sleep(FIELD_SETTLE_SECONDS)
                    return

    trigger_xpath = (
        f"//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        f"'abcdefghijklmnopqrstuvwxyz'), {lower_label!r})]"
        "/following::*[self::button or @role='button' or contains(@class, 'select') "
        "or contains(@class, 'dropdown')][1]"
    )

    try:
        trigger = find_first(wait, [(By.XPATH, trigger_xpath)], label_text, must_be_clickable=True)
        browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", trigger)
        trigger.click()
    except TimeoutException:
        click_text(wait, label_text, label_text)

    option_xpath = (
        f"//*[self::li or self::div or self::span or self::button]"
        f"[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        f"'abcdefghijklmnopqrstuvwxyz'), {lower_option!r})]"
    )
    option = find_first(wait, [(By.XPATH, option_xpath)], f"{label_text} option {option_text}", must_be_clickable=True)
    browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
    option.click()
    time.sleep(FIELD_SETTLE_SECONDS)


def upload_thumbnail(wait, browser, image_path):
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Thumbnail image not found: {image_path}")

    upload_inputs = browser.find_elements(By.CSS_SELECTOR, "input[type='file']")
    if not upload_inputs:
        try:
            click_text(wait, "Add Thumbnail", "Add Thumbnail button")
        except TimeoutException:
            click_text(wait, "Thumbnail", "Thumbnail button")
        upload_inputs = browser.find_elements(By.CSS_SELECTOR, "input[type='file']")

    if not upload_inputs:
        print_page_debug(browser, "thumbnail file upload input")
        raise TimeoutException("Could not find thumbnail file upload input")

    upload_inputs[0].send_keys(image_path)
    time.sleep(1.5)


def fill_blog_content(wait, browser, content):
    locators = [
        (By.CSS_SELECTOR, "textarea[name*='content' i]"),
        (By.CSS_SELECTOR, "textarea[id*='content' i]"),
        (By.CSS_SELECTOR, ".jodit-wysiwyg"),
        (By.CSS_SELECTOR, "[contenteditable='true']"),
        (By.CSS_SELECTOR, ".ql-editor"),
        (By.CSS_SELECTOR, ".tox-edit-area iframe"),
        (By.CSS_SELECTOR, "iframe"),
    ]

    editor = find_first(wait, locators, "blog content editor")
    browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", editor)

    set_html_script = """
        const el = arguments[0];
        const value = arguments[1];
        const marker = arguments[2];
        const result = {
            joditInstances: 0,
            tinymceEditors: 0,
            ckeditorInstances: 0,
            quillEditors: 0,
            textareas: 0,
            editableNodes: 0,
            markerFound: false,
            savedValueFound: false,
        };

        function normalizeImages(root) {
            if (!root || !root.querySelectorAll) return;
            root.querySelectorAll('img').forEach((img) => {
                const declaredWidth = img.getAttribute('width') || '602';
                img.style.width = declaredWidth + 'px';
                img.style.maxWidth = '100%';
                img.style.height = 'auto';
                img.style.display = 'block';
                img.style.margin = '30px auto';
            });
        }

        function notify(target) {
            if (!target) return;
            target.dispatchEvent(new Event('input', { bubbles: true }));
            target.dispatchEvent(new Event('change', { bubbles: true }));
            target.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
            target.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
        }

        function setElementHtml(target) {
            if (!target) return;
            if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') {
                const descriptor = Object.getOwnPropertyDescriptor(
                    Object.getPrototypeOf(target),
                    'value'
                );
                if (descriptor && descriptor.set) {
                    descriptor.set.call(target, value);
                } else {
                    target.value = value;
                }
            } else {
                target.innerHTML = value;
                normalizeImages(target);
            }
            notify(target);
        }

        function valueHasMarker(target) {
            if (!target) return false;
            return String(target.value || target.innerText || target.innerHTML || '').includes(marker);
        }

        if (window.Jodit && window.Jodit.instances) {
            const instances = Object.values(window.Jodit.instances);
            instances.forEach((instance) => {
                result.joditInstances += 1;
                instance.value = value;
                if (typeof instance.setEditorValue === 'function') instance.setEditorValue(value);
                if (instance.editor) {
                    instance.editor.innerHTML = value;
                    normalizeImages(instance.editor);
                    notify(instance.editor);
                }
                if (instance.element) {
                    instance.element.value = value;
                    notify(instance.element);
                }
                if (typeof instance.synchronizeValues === 'function') instance.synchronizeValues();
                if (typeof instance.e?.fire === 'function') instance.e.fire('change');
                result.savedValueFound = result.savedValueFound
                    || String(instance.value || '').includes(marker)
                    || valueHasMarker(instance.element);
            });
        }

        if (el.jodit) {
            result.joditInstances += 1;
            el.jodit.value = value;
            if (typeof el.jodit.setEditorValue === 'function') el.jodit.setEditorValue(value);
            if (el.jodit.editor) {
                el.jodit.editor.innerHTML = value;
                normalizeImages(el.jodit.editor);
                notify(el.jodit.editor);
            }
            if (el.jodit.element) {
                el.jodit.element.value = value;
                notify(el.jodit.element);
            }
            if (typeof el.jodit.synchronizeValues === 'function') el.jodit.synchronizeValues();
            if (typeof el.jodit.e?.fire === 'function') el.jodit.e.fire('change');
            result.savedValueFound = result.savedValueFound
                || String(el.jodit.value || '').includes(marker)
                || valueHasMarker(el.jodit.element);
        }

        if (window.tinymce && window.tinymce.editors) {
            window.tinymce.editors.forEach((editor) => {
                result.tinymceEditors += 1;
                editor.setContent(value);
                editor.save();
                editor.fire('input');
                editor.fire('change');
                result.savedValueFound = result.savedValueFound
                    || String(editor.getContent() || '').includes(marker)
                    || valueHasMarker(document.getElementById(editor.id));
            });
        }

        if (window.CKEDITOR && window.CKEDITOR.instances) {
            Object.values(window.CKEDITOR.instances).forEach((editor) => {
                result.ckeditorInstances += 1;
                editor.setData(value);
                editor.updateElement();
                editor.fire('change');
                result.savedValueFound = result.savedValueFound
                    || String(editor.getData() || '').includes(marker)
                    || valueHasMarker(editor.element && editor.element.$);
            });
        }

        document.querySelectorAll('.ql-editor').forEach((node) => {
            const container = node.closest('.ql-container');
            const quill = container && container.__quill;
            if (quill) {
                result.quillEditors += 1;
                quill.clipboard.dangerouslyPasteHTML(value);
                quill.root.dispatchEvent(new Event('input', { bubbles: true }));
                quill.root.dispatchEvent(new Event('change', { bubbles: true }));
                result.savedValueFound = result.savedValueFound
                    || String(quill.root.innerHTML || '').includes(marker);
            }
        });

        if (window.Livewire && typeof window.Livewire.all === 'function') {
            window.Livewire.all().forEach((component) => {
                const snapshot = component.snapshot || {};
                Object.keys(snapshot.data || {}).forEach((key) => {
                    if (key.toLowerCase().includes('content') && typeof component.set === 'function') {
                        component.set(key, value);
                    }
                });
            });
        }

        setElementHtml(el);

        document.querySelectorAll(
            'textarea[name*="content" i], textarea[id*="content" i], textarea'
        ).forEach((textarea) => {
            result.textareas += 1;
            textarea.value = value;
            notify(textarea);
            result.savedValueFound = result.savedValueFound || valueHasMarker(textarea);
        });

        document.querySelectorAll(
            '.jodit-wysiwyg, [contenteditable="true"], .ql-editor'
        ).forEach((node) => {
            result.editableNodes += 1;
            node.innerHTML = value;
            normalizeImages(node);
            notify(node);
        });

        result.markerFound = document.body.innerText.includes(marker)
            || document.body.innerHTML.includes(marker);
        document.activeElement && document.activeElement.blur && document.activeElement.blur();
        return result;
    """

    tag_name = editor.tag_name.lower()
    if tag_name == "iframe":
        browser.switch_to.frame(editor)
        body = find_first(wait, [(By.CSS_SELECTOR, "body")], "editor body")
        result = browser.execute_script(
            """
            document.body.innerHTML = arguments[0];
            document.body.querySelectorAll('img').forEach((img) => {
                const declaredWidth = img.getAttribute('width') || '602';
                img.style.width = declaredWidth + 'px';
                img.style.maxWidth = '100%';
                img.style.height = 'auto';
                img.style.display = 'block';
                img.style.margin = '30px auto';
            });
            document.body.dispatchEvent(new Event('input', { bubbles: true }));
            document.body.dispatchEvent(new Event('change', { bubbles: true }));
            document.body.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
            return {
                markerFound: document.body.innerText.includes(arguments[1])
                    || document.body.innerHTML.includes(arguments[1]),
                savedValueFound: false
            };
            """,
            content,
            "The demand for flexible",
        )
        browser.switch_to.default_content()
        print(f"Blog content insert check: {result}")
        time.sleep(1.5)
        return

    result = browser.execute_script(set_html_script, editor, content, "The demand for flexible")
    print(f"Blog content insert check: {result}")

    if not result or not result.get("markerFound"):
        print_page_debug(browser, "blog content insertion")
        raise RuntimeError("Blog content was not detected in the editor after insertion.")

    if not result.get("savedValueFound"):
        print(
            "Warning: content is visible in the editor, but the hidden saved value "
            "could not be confirmed. Click inside the editor/preview once if this "
            "site requires it before submitting."
        )
    time.sleep(1.5)


def switch_to_login_frame(browser):
    browser.switch_to.default_content()

    if browser.find_elements(By.CSS_SELECTOR, "input"):
        return

    frames = browser.find_elements(By.CSS_SELECTOR, "iframe, frame")
    for frame in frames:
        browser.switch_to.default_content()
        browser.switch_to.frame(frame)
        if browser.find_elements(By.CSS_SELECTOR, "input"):
            print("Found login form inside a frame.")
            return

    browser.switch_to.default_content()


def read_auth_storage(browser):
    return browser.execute_script(
        """
        function collectStorage(storage, prefix) {
            const values = {};
            for (let index = 0; index < storage.length; index += 1) {
                const key = storage.key(index);
                values[`${prefix}.${key}`] = storage.getItem(key);
            }
            return values;
        }

        function inspectValue(value, state, path) {
            if (value === null || value === undefined) return;
            if (typeof value === 'string') {
                if (value.toUpperCase() === 'AUTHOR') state.role = 'AUTHOR';
                if (value.length > 10 && /token|jwt/i.test(path)) state.hasToken = true;
                return;
            }
            if (typeof value !== 'object') return;

            Object.entries(value).forEach(([key, child]) => {
                const childPath = path ? `${path}.${key}` : key;
                if (/role/i.test(key) && String(child).toUpperCase() === 'AUTHOR') {
                    state.role = 'AUTHOR';
                }
                if (/(^|_)(id|userId|authorId)$/i.test(key) && child && child !== 'null') {
                    state.id = String(child);
                    state.idPath = childPath;
                }
                inspectValue(child, state, childPath);
            });
        }

        const rawValues = {
            ...collectStorage(window.localStorage, 'localStorage'),
            ...collectStorage(window.sessionStorage, 'sessionStorage'),
        };
        const state = { hasToken: false, role: null, id: null, idPath: null, keys: Object.keys(rawValues) };

        Object.entries(rawValues).forEach(([key, rawValue]) => {
            if (/token|jwt/i.test(key) && rawValue) state.hasToken = true;
            if (/role/i.test(key) && String(rawValue).toUpperCase() === 'AUTHOR') state.role = 'AUTHOR';
            if (/(^|_)(id|userId|authorId)$/i.test(key) && rawValue && rawValue !== 'null') {
                state.id = String(rawValue);
                state.idPath = key;
            }

            try {
                inspectValue(JSON.parse(rawValue), state, key);
            } catch (error) {
                inspectValue(rawValue, state, key);
            }
        });

        return state;
        """
    )


def wait_for_author_context(browser):
    print("Waiting for author login/profile context to settle...")
    wait = WebDriverWait(browser, 8)

    try:
        state = wait.until(
            lambda driver: (
                read_auth_storage(driver)
                if read_auth_storage(driver).get("hasToken")
                and read_auth_storage(driver).get("role") == "AUTHOR"
                and read_auth_storage(driver).get("id")
                else False
            )
        )
        print(f"Author context ready. ID source: {state.get('idPath')}")
        return
    except TimeoutException:
        state = read_auth_storage(browser)
        if state.get("hasToken") and state.get("role") == "AUTHOR":
            print(
                "Author token/role are ready. ID was not visible in browser storage, "
                "but the site can still load it from the /me API. Continuing..."
            )
            time.sleep(2)
            return

        print(
            "Warning: author context may not be fully ready. "
            f"token={state.get('hasToken')} role={state.get('role')} id={state.get('id')}"
        )
        input(
            "If the dashboard/profile is still loading, wait in the browser. "
            "Press Enter when ready to start creating blogs..."
        )


def login(browser, username, password):
    wait = WebDriverWait(browser, WAIT_SECONDS)

    try:
        browser.get(LOGIN_URL)
        print(f"Opened: {browser.current_url}")
    except WebDriverException as error:
        raise RuntimeError(
            "Chrome opened but disconnected before the login page loaded. "
            "Close all Chrome windows started by this script and run it again. "
            "If it still happens, update Chrome and Selenium with: "
            "pip install --upgrade selenium"
        ) from error

    switch_to_login_frame(browser)

    print("Looking for username/phone field...")
    try:
        username_field = find_first(
            wait,
            [
                (By.NAME, "email"),
                (By.NAME, "username"),
                (By.NAME, "userName"),
                (By.NAME, "mobile"),
                (By.NAME, "phone"),
                (By.ID, "email"),
                (By.ID, "username"),
                (By.ID, "mobile"),
                (By.ID, "phone"),
                (By.CSS_SELECTOR, "input[type='email']"),
                (By.CSS_SELECTOR, "input[type='tel']"),
                (By.CSS_SELECTOR, "input[type='text']"),
                (
                    By.XPATH,
                    "//input[contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'email') "
                    "or contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'user') "
                    "or contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'mobile') "
                    "or contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'phone')]",
                ),
            ],
            "username/email/mobile field",
        )
    except TimeoutException:
        print_page_debug(browser)
        raise
    username_field.clear()
    username_field.send_keys(username)
    print("Entered username/phone.")

    print("Looking for password field...")
    password_field = find_first(
        wait,
        [
            (By.NAME, "password"),
            (By.NAME, "Password"),
            (By.ID, "password"),
            (By.ID, "Password"),
            (By.CSS_SELECTOR, "input[type='password']"),
        ],
        "password field",
    )
    password_field.clear()
    password_field.send_keys(password)
    print("Entered password.")

    print("Looking for Get/Send OTP button...")
    request_otp(wait, browser, password_field)

    print("\nOTP requested.")
    print("Enter the OTP in the browser, click the next/login button there,")
    input("then press Enter here after the dashboard/blog page opens...")

    time.sleep(1)
    print(f"Current page: {browser.current_url}")
    wait_for_author_context(browser)


def wait_for_manual_fix_then_submit(wait, browser, place, error):
    print(f"\nProblem while creating blog for {place}: {error}")
    print("The browser will stay on this blog form so you can fix it manually.")

    while True:
        choice = input(
            "After fixing the form, press Enter to submit it. "
            "Type 'done' if you already submitted it, 'skip' to skip this place, "
            "or 'debug' to print page details: "
        ).strip().lower()

        if choice in {"skip", "s"}:
            print(f"Skipped {place}.")
            return False

        if choice in {"done", "d"}:
            print(f"Marked {place} as submitted.")
            return True

        if choice == "debug":
            print_page_debug(browser, f"manual fix for {place}")
            continue

        try:
            submit_for_review(wait, browser)
            return True
        except Exception as submit_error:
            print(f"Submit still failed for {place}: {submit_error}")
            print("Fix anything still missing in the browser, then try again.")


def wait_before_submit(wait, browser, place):
    print(f"Details filled for {place}. Waiting before submit.")

    while True:
        choice = input(
            "Press Enter/Resume to submit now. Type 'done' if you already submitted it, "
            "'skip' to skip this place, or 'debug' to print page details: "
        ).strip().lower()

        if choice in {"skip", "s"}:
            print(f"Skipped {place}.")
            return "skip"

        if choice in {"done", "d"}:
            print(f"Marked {place} as submitted.")
            return "done"

        if choice == "debug":
            print_page_debug(browser, f"pre-submit check for {place}")
            continue

        return "submit"


def consume_pause_before_submit():
    global PAUSE_BEFORE_NEXT_SUBMIT
    if not PAUSE_BEFORE_NEXT_SUBMIT:
        return False
    PAUSE_BEFORE_NEXT_SUBMIT = False
    return True


def create_blog_for_place(browser, template_content, place, index, total):
    if not os.path.exists(BLOG_CONTENT_PATH):
        raise FileNotFoundError(f"Blog content file not found: {BLOG_CONTENT_PATH}")

    current_blog_title = blog_title(place)
    blog_content = content_for_place(template_content, place)

    wait = WebDriverWait(browser, WAIT_SECONDS)
    browser.switch_to.default_content()

    print(f"\nCreating blog {index}/{total}: {current_blog_title}")
    try:
        print("Opening fresh Create Blog page...")
        browser.get("https://blog.vidyarishi.com/author/create")
        time.sleep(1.5)
        open_create_blog_page(wait, browser)

        print("Entering blog title...")
        set_blog_title(wait, browser, current_blog_title)

        print("Uploading thumbnail...")
        upload_thumbnail(wait, browser, THUMBNAIL_PATH)

        print("Selecting blog category...")
        select_dropdown_value(wait, browser, "Blog Category", BLOG_CATEGORY)

        print("Selecting tag...")
        select_dropdown_value(wait, browser, "Tag", BLOG_TAG)

        fill_seo_settings(wait, browser, place)

        open_write_blog(wait, browser)

        print(f"Pasting blog content from {os.path.basename(BLOG_CONTENT_PATH)}...")
        fill_blog_content(wait, browser, blog_content)

        if consume_pause_before_submit():
            pre_submit_action = wait_before_submit(wait, browser, place)
            if pre_submit_action == "skip":
                return False
            if pre_submit_action == "done":
                return blog_path(place)
    except Exception as error:
        return wait_for_manual_fix_then_submit(wait, browser, place, error)

    for duplicate_attempt in range(0, 10):
        try:
            submit_for_review(wait, browser)
            suffix = roman_numeral(duplicate_attempt) if duplicate_attempt else None
            return blog_path(place, suffix)
        except DuplicateBlogError as error:
            suffix = roman_numeral(duplicate_attempt + 1)
            retry_title = title_with_suffix(place, suffix)
            print(
                f"Blog title already exists. Retrying with title only changed to: {retry_title}"
            )
            try:
                set_blog_title(wait, browser, retry_title)
            except Exception as title_error:
                return wait_for_manual_fix_then_submit(wait, browser, place, title_error)
            continue
        except Exception as error:
            return wait_for_manual_fix_then_submit(wait, browser, place, error)

    return wait_for_manual_fix_then_submit(
        wait,
        browser,
        place,
        "Could not find an unused Roman numeral title suffix after 10 attempts.",
    )


def create_blogs(browser):
    if not os.path.exists(BLOG_CONTENT_PATH):
        raise FileNotFoundError(f"Blog content file not found: {BLOG_CONTENT_PATH}")

    with open(BLOG_CONTENT_PATH, "r", encoding="utf-8") as content_file:
        template_content = prepare_blog_content(content_file.read())

    places = parse_places()
    print(f"Places to process: {', '.join(places)}")

    run_started_at = time.perf_counter()
    submitted_count = 0
    skipped_count = 0
    failed_count = 0
    confirmed_blog_paths = []
    skipped_blog_paths = []
    failed_blog_paths = []

    for index, place in enumerate(places, start=1):
        try:
            confirmed_path = create_blog_for_place(browser, template_content, place, index, len(places))
            if confirmed_path:
                submitted_count += 1
                if confirmed_path is True:
                    confirmed_path = blog_path(place)
                confirmed_blog_paths.append(confirmed_path)
            else:
                skipped_count += 1
                skipped_blog_paths.append(blog_path(place))
        except Exception as error:
            print(f"Failed {place}: {error}")
            failed_count += 1
            failed_blog_paths.append(blog_path(place))

    with open(CONFIRMED_BLOGS_OUTPUT_PATH, "w", encoding="utf-8") as output_file:
        output_file.write("\n".join(confirmed_blog_paths))
    with open(SKIPPED_BLOGS_OUTPUT_PATH, "w", encoding="utf-8") as output_file:
        output_file.write("\n".join(skipped_blog_paths))
    with open(FAILED_BLOGS_OUTPUT_PATH, "w", encoding="utf-8") as output_file:
        output_file.write("\n".join(failed_blog_paths))

    elapsed_seconds = time.perf_counter() - run_started_at
    processed_count = submitted_count + skipped_count + failed_count
    average_seconds = elapsed_seconds / processed_count if processed_count else 0
    success_rate = (submitted_count / len(places) * 100) if places else 0
    history_record = {
        "startedAt": datetime.now().isoformat(timespec="seconds"),
        "total": len(places),
        "processed": processed_count,
        "submitted": submitted_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "elapsedSeconds": round(elapsed_seconds, 2),
        "averageSecondsPerBlog": round(average_seconds, 2),
        "successRate": round(success_rate, 2),
        "confirmedOutput": CONFIRMED_BLOGS_OUTPUT_PATH,
        "skippedOutput": SKIPPED_BLOGS_OUTPUT_PATH,
        "failedOutput": FAILED_BLOGS_OUTPUT_PATH,
    }
    append_run_history(history_record)

    print("\n========== Run Summary ==========")
    print(f"Total places:       {len(places)}")
    print(f"Processed:          {processed_count}")
    print(f"Submitted:          {submitted_count}")
    print(f"Skipped:            {skipped_count}")
    print(f"Failed:             {failed_count}")
    print(f"Success rate:       {success_rate:.1f}%")
    print(f"Elapsed time:       {format_duration(elapsed_seconds)}")
    print(f"Average per blog:   {average_seconds:.1f}s")
    print("Output files:")
    print(f"  Confirmed:        {CONFIRMED_BLOGS_OUTPUT_PATH}")
    print(f"  Skipped:          {SKIPPED_BLOGS_OUTPUT_PATH}")
    print(f"  Failed:           {FAILED_BLOGS_OUTPUT_PATH}")
    print(f"History:            {RUN_HISTORY_PATH}")
    print("=================================")
    print(
        f"Batch complete. Submitted: {submitted_count}. "
        f"Skipped: {skipped_count}. Failed: {failed_count}."
    )
    print(
        "Run analytics: "
        f"total={len(places)}, processed={processed_count}, "
        f"elapsed={elapsed_seconds:.1f}s, average={average_seconds:.1f}s/blog, "
        f"success={success_rate:.1f}%."
    )
    if not IN_GUI_MODE:
        input("Press Enter here when you want to close the script...")


def main():
    load_dotenv(override=True)

    username = env_value("VIDYARISHI_USERNAME", "USERNAME", "EMAIL", "PHONE")
    password = env_value("VIDYARISHI_PASSWORD", "PASSWORD")

    if not username or not password:
        raise RuntimeError(
            "Missing credentials. Add VIDYARISHI_USERNAME and "
            "VIDYARISHI_PASSWORD to your .env file."
        )

    try:
        browser = build_browser()
        login(browser, username, password)
        create_blogs(browser)
    except InvalidSessionIdException as error:
        raise RuntimeError(
            "Chrome closed or crashed before Selenium could use it. "
            "Close the Selenium Chrome window, then run the script again. "
            "If it repeats, run: pip install --upgrade selenium"
        ) from error


if __name__ == "__main__":
    main()
