# Vidyarishi Blog Automation

Desktop automation for creating Vidyarishi blog posts from a Word/HTML template. It uses Selenium to control Chrome and a Tkinter frontend for starting runs, editing places, pausing before submit, viewing logs, and reviewing output/history.

## What It Does

- Logs in to `https://blog.vidyarishi.com/login`
- Lets you manually complete OTP in Chrome
- Creates blog posts for every place in `.env`
- Fills title, thumbnail, category, tag, SEO settings, and blog content
- Compresses Word document images when generating HTML
- Handles long meta titles/descriptions
- Retries duplicate blog titles using Roman numerals like `- I`, `- II`
- Writes confirmed, skipped, and failed blog paths to output files
- Keeps run analytics/history

## Files

```text
vidyarishi_gui.py        Tkinter frontend
vidyarishi_login.py      Main Selenium automation
docx_to_blog_html.py     Converts Blog Title.docx to HTML with compressed images
Blog Title.docx          Source blog template
hello_with_images.html   Generated blog content used by the automation
hello.txt                Fallback text-only content
public/thumbnail mba.jpg Blog thumbnail image
requirements.txt         Python packages
.env.example             Example environment file
```

Generated/local files:

```text
.env                     Your real credentials and places, not committed to GitHub
confirmed_blogs.csv      One confirmed blog path per line
skipped_blogs.csv        One skipped blog path per line
failed_blogs.csv         One failed blog path per line
run_history.jsonl        Run history and analytics
```

## First-Time Setup

Open Command Prompt in the project folder:

```cmd
cd "C:\Users\jaggi\OneDrive\Desktop\internship work"
```

Install dependencies:

```cmd
python -m pip install -r requirements.txt
```

If `python` is not found, install Python from:

```text
https://www.python.org/downloads/
```

During install, enable:

```text
Add python.exe to PATH
```

Also make sure Google Chrome is installed.

## Configure `.env`

Create `.env` from `.env.example` if needed:

```cmd
copy .env.example .env
```

Open it:

```cmd
notepad .env
```

Example:

```text
VIDYARISHI_USERNAME=your_username_or_phone
VIDYARISHI_PASSWORD=your_password
PLACES=Tatgarh,Basapura,Kumaraswamy Layout
```

You can also edit places from the GUI using **Edit Places**.

## Run With Frontend

Recommended:

Double-click:

```text
Vidyarishi Blog Studio.lnk
```

Or run from CMD:

```cmd
python vidyarishi_gui.py
```

Then:

1. Click **Start Run**
2. Chrome opens the Vidyarishi login page
3. Enter OTP manually in Chrome
4. After dashboard opens, click **Continue After OTP** in the GUI
5. The automation runs through the places
6. Use **Pause Before Next Submit** only if you want to inspect the next blog before submit
7. If paused:
   - **Resume: Submit This Blog** lets the script submit
   - **Done: I Submitted Manually** marks it as submitted
   - **Skip This Place** skips it
   - **Debug Page Details** prints visible page details

## Run Without Frontend

You can still run the terminal version:

```cmd
python vidyarishi_login.py
```

The GUI is easier for long batches.

## Regenerate Blog HTML From Word

If you edit `Blog Title.docx`, regenerate the HTML:

```cmd
python docx_to_blog_html.py "Blog Title.docx" --out hello_with_images.html
```

This compresses inline images so the backend does not reject the blog request as too large.

## Output Files

After a run:

```text
confirmed_blogs.csv
skipped_blogs.csv
failed_blogs.csv
run_history.jsonl
```

Each blog path is on a separate line, for example:

```text
/online-mba-in-tatgarh
/online-mba-in-basapura
```

The GUI **Outputs** tab shows confirmed/skipped/failed paths. The **History** tab shows previous run analytics.

## GitHub Transfer To Another Laptop

Do not upload `.env`. It contains credentials. `.gitignore` already excludes it.

First upload:

```cmd
cd "C:\Users\jaggi\OneDrive\Desktop\internship work"
git init
git add .
git commit -m "Initial Vidyarishi blog automation"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git push -u origin main
```

On another laptop:

```cmd
cd "%USERPROFILE%\Desktop"
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
cd YOUR_REPO_NAME
python -m pip install -r requirements.txt
copy .env.example .env
notepad .env
python vidyarishi_gui.py
```

Fill `.env` with real credentials and places before running.

## Updating Another Laptop Later

On the main laptop:

```cmd
git add .
git commit -m "Update automation"
git push
```

On the other laptop:

```cmd
git pull
python -m pip install -r requirements.txt
python vidyarishi_gui.py
```

## Troubleshooting

If Chrome/Selenium fails:

```cmd
python -m pip install --upgrade selenium
```

If images disappear:

```cmd
python docx_to_blog_html.py "Blog Title.docx" --out hello_with_images.html
```

If the backend says payload too large, the images/content are too large. Regenerate the HTML, or reduce images in the Word document.

If a blog title already exists, the script retries by changing only the title:

```text
Online MBA in Place - I
Online MBA in Place - II
```

If a long meta title fails, the script shortens it automatically.

## Notes

- Keep Chrome DevTools closed during large runs for better speed.
- Use **Pause Before Next Submit** only when you want to inspect the next blog.
- The automation auto-submits by default.
- `.env`, outputs, and run history are intentionally not committed to GitHub.
