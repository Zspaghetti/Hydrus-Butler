# Hydrus Butler: Your Personal Library Automation Assistant!


Tired of manual repetitive library chores? **Hydrus Butler** is a Flask-based web application that automates tasks within your [Hydrus Network](https://hydrusnetwork.github.io/hydrus/) library. Using a User-Friendly Web UI, easily define powerful rules and let the Butler manage your file domains, tags, and ratings of your files effortlessly – automatically or on demand!

**Give your assistant a unique Butler Name!** Choose from **9 themes** (including the Neon theme!) to style the interface. Let the Butler run your rules automatically at your chosen frequency, keeping your library perfectly organized.

---

## Table of Contents

1.  [🚀 Quick Start & Setup](#-quick-start--setup)
2.  [⚠️ Important First Steps & Advice](#️-important-first-steps--advice)
3.  [💡 What Can Butler Do For You?](#-what-can-butler-do-for-you)
4.  [💬 Feedback & Issues](#-feedback--issues)
5.  [📜 License](#-license)

---

## 🚀 Quick Start & Setup

1.  **Prerequisites:**
    *   Python 3.7+ installed on your system.
    *   [Hydrus Network](https://github.com/hydrusnetwork/hydrus) client installed, running, and with its API enabled.

2.  **Download/Clone Hydrus Butler:** 
`git clone https://github.com/Zspaghetti/Hydrus-Butler` or download the code's zip and extract it.

3.  **Run the Startup Script:**
    *   **For Windows Users:**
        *   Navigate to the Hydrus Butler directory.
        *   Double-click `start_windows.bat`.
    *   **For macOS/Linux Users:**
        1.  Open a terminal and navigate to the Hydrus Butler directory.
        2.  Make the script executable (you only need to do this once):
            ```bash
            chmod +x start_macOS.sh
            ```
        3.  Run the script:
            ```bash
            ./start_macOS.sh
            ```
			
4.  **Access Hydrus Butler:**
    *   Navigate to: `http://127.0.0.1:5556/` in you web browser. 

5.  **Initial Butler Configuration:**
    *   In the Hydrus Butler web interface, go to the **Settings** page. Enter your Hydrus Client **API Address** (e.g., `http://localhost:45869`) and **API Key**.
    *   Adjust other preferences and  Click Save Settings. As soon as Hydrus Butler correctly fetches your Hydrus services, you're now ready to set up your first rule!
---

## ⚠️ Important First Steps & Advice

*   **BACKUP YOUR HYDRUS DATABASE!** Before launching Hydrus Butler for the first time, and do it regularly.
*   Run new rules manually once: Processing a large number of files can take time. Run a new rule manually to ensure it works as intended before automation.
*   Hydrus Butler can use complex conditions like tag presence in a specific tag service (e.g., `system:has tag in "my tags", ignoring siblings/parents: "test"`) and more, for this use the "Paste Search" condition.
*   A database is here to solve incompatible rules using the priority system. (e.g., `Set rating "like": 1/2` and `Set rating "like": 2/2` for a same file)
*   If you meet a particular problem, please open an issue on GitHub or ask on the Hydrus Discord (or PM).

---

## 💡 What Can Butler Do For You?

**Conditions:**
Tags, Ratings (liked/disliked, numerical, has/no), File Services, File Properties (size, inbox, archive, local, trashed, audio, EXIF, notes), URLs (existence, count, regex), Filetypes (categories/extensions), OR Groups, Paste Search (direct Hydrus queries).

**Actions:**
`add_to` (Copy to file services), `force_in` (Move between local file services), `add_tags`, `remove_tags`, `modify_rating`.

-> As a file gets a high enough "likeability" rating, it can get sent to the domain 'My fav collection'!

-> If a new file has one of your favourite tags, send it to the domain 'Must check ASAP'. If it has one or multiple tag(s) you don't like though, Force it into 'Badge' and nowhere else!

-> You assigned a particular tag to your subscription files and want it removed or replaced? Changed into a rating?

-> You want to add tags based on current tags? Or perhaps based on import date?


Hydrus Butler is at your service!
 

## 💬 Feedback & Issues

Feel free to post an issue on GitHub about anything: use cases, bugs, feature requests, or even the weather forecast! Your feedback is valuable.

---

## 📜 License

License: TBD
