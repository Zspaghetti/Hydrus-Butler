# Hydrus Butler: Your Personal Library Automation Assistant!


Tired of manual repetitive library chores? **Hydrus Butler** is a Flask-based web application that automates tasks within your [Hydrus Network](https://hydrusnetwork.github.io/hydrus/) library. Using a User-Friendly Web UI, easily define powerful rules and let the Butler manage your file domains, tags, and ratings of your files effortlessly – automatically or on demand!

**Hydrus Butler** doesn't edit, add or delete your files, it only edit their metadata in Hydrus. **Hydrus Butler** works by making searches based on your conditions, and edit returned files metadata based on the actions you define using the Hydrus API. 

**Give your assistant a unique Butler Name!** Choose from **9 themes** (including the Neon theme!) to style the interface. Let the Butler run your rules automatically at your chosen frequency, keeping your library perfectly organized.

---

## Table of Contents

1.  [🚀 Quick Start & Setup](#-quick-start--setup)
2.  [⚠️ Important First Steps & Advice](#️-important-first-steps--advice)
3. [💡 How Can Butler Assist You?](#-how-can-butler-assist-you)
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

## 💡 How Can Butler Assist You?

Hydrus Butler helps automate your file organization by observing specific file characteristics and performing actions you define.

**Butler Can Recognize (Conditions):**
*   **Tags:** Specific tags present or absent.
*   **Ratings:** Liked/disliked status, numerical scores, or whether a rating exists.
*   **File Services:** Which services a file is currently part of.
*   **File Properties:** Details like size, inbox/archive status, local availability, trashed status, audio presence, EXIF data, and notes.
*   **URLs:** Existence, count, or matches against regular expressions.
*   **Filetypes:** Broad categories or specific extensions.
*   **OR Groups:** Combinations of the above conditions.
*   **Paste Search:** Direct Hydrus query results.

**And Then Butler Can (Actions):**
*   `add_to`: Copy files to additional file services.
*   `force_in`: Move files exclusively to a specific local file service (removing from others).
*   `add_tags`: Apply new tags.
*   `remove_tags`: Take away existing tags.
*   `modify_rating`: Change or set a file's rating.

**For example, Butler can help you:**

➡️ **Curate Collections:** As a file accumulates a high "likeability" rating, Butler can automatically copy it to your 'My fav collection' domain.

➡️ **Prioritize New Files:** If a new file arrives with one of your favourite tags, Butler can send it to the 'Must check ASAP' domain. If it unfortunately has tags you'd prefer to avoid, Butler can ensure it's neatly filed into 'Badge' and kept separate.

➡️ **Streamline Tag Management:** Do you have subscription files with tags that need updating? Butler can automatically remove or replace them, or even convert a tag into a rating.

➡️ **Automate Tagging Logic:** Would you like to add new tags based on existing ones, or perhaps based on a file's import date? Butler can handle this for you.

Hydrus Butler is at your service!
 

## 💬 Feedback & Issues

Feel free to post an issue on GitHub about anything: use cases, bugs, feature requests, or even the weather forecast! Your feedback is valuable.

---

## 📜 License

License: TBD
