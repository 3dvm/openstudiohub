# OpenStudioHub: Pipeline Management System

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)
![Blender](https://img.shields.io/badge/Blender-3.6_|_4.2_|_5.1-orange?logo=blender&logoColor=white)
![Kitsu](https://img.shields.io/badge/Kitsu_SSO-Gazu-success?logo=cgwire&logoColor=white)
![Architecture](https://img.shields.io/badge/Architecture-MVC-purple)

**OpenStudioHub** is a standalone desktop application designed to orchestrate the production pipeline for a 3D animation studio. It acts as a seamless, deterministic bridge between artists, the version control system (SVN/NAS), and the production tracker (Kitsu).

> **[![Watch the Demo Video Showcase Here](https://img.youtube.com/vi/k9OS4430Rp8/maxresdefault.jpg)](https://www.youtube.com/watch?v=k9OS4430Rp8)**

---

## The Elephant in the Room: Blender Studio Tools

Any studio working with Blender has looked with envy at the Blender Foundation's official pipeline. Tools like the `asset_pipeline` (designed to enable simultaneous work on the same asset) and `blender_kitsu` (which connects the 3D interface directly with the production manager) are, on paper, a Technical Director's dream come true.

However, there is an "elephant in the room" that few talk about: **these tools are not *plug-and-play*.**

Implementing the Blender Studio Tools ecosystem outside the Foundation's walls requires overcoming a brutal technical learning curve. If your studio doesn't replicate their exact network infrastructure, use their strict SVN configuration, or if you have artists working remotely on Windows instead of Linux, integration usually ends in broken scripts, lost paths, and hours of frustration for the IT team.

Here is where **OpenStudioHub** comes in. Designed under a "zero friction" philosophy, it doesn't seek to reinvent the wheel, but to tame it. It works as a smart Sandbox environment that packages, pre-configures, and standardizes these powerful core tools, making them accessible to any studio—from an indie team to a mid-sized production company—with just a couple of clicks.

---

## The Problem: Changing Blender versions.
In large-scale productions, updating software versions or add-ons mid-show often breaks backward compatibility. Artists waste hours dealing with Python tracebacks, missing add-ons, and manual path configurations just to open a legacy file without corrupting modern production data.

## The Solution: An Ephemeral Sandbox
OpenStudioHub solves this by reading a configuration file (`project_config.json`) of each project and **building dynamic software containers at runtime**. It bypasses global OS installations completely by injecting environment variables to isolate extensions, wheels, and preferences per project. 

This guarantees **100% backward compatibility** and allows artists to run conflicting legacy tools (e.g., Blender 3.6) and modern pipelines (e.g., Blender 5.2) simultaneously with zero cross-contamination.

---

## High-Level Studio Architecture

```mermaid
flowchart TD

    classDef actor fill:#ffa94d,stroke:#1e1e1e,stroke-width:2px,color:#1e1e1e
    classDef hub fill:#a5d8ff,stroke:#1e1e1e,stroke-width:2px,color:#1e1e1e
    classDef tracker fill:#b2f2bb,stroke:#1e1e1e,stroke-width:2px,color:#1e1e1e
    classDef app fill:#ffc9c9,stroke:#1e1e1e,stroke-width:2px,color:#1e1e1e
    classDef storage fill:#ffec99,stroke:#1e1e1e,stroke-width:2px,color:#1e1e1e

    subgraph SystemContainer
        direction LR
        
        Title["<span style='font-size: 30px; font-weight: bold;'>OpenStudioHub System Diagram</span>"]:::titleStyle

        %% Actors (Orange)
        TD_User[Technical Director]:::actor
        PM_User[Production Manager]:::actor
        ED_User[Editor]:::actor
        AR_User[Artist]:::actor
    
        %% Central Hub (Blue Diamond)
        OSH{OpenStudioHub}:::hub
    
        %% Tools and Services (Green, Red, Yellow)
        Kitsu[(Kitsu / Production\ntracking DB)]:::tracker
        WT((WatchTower)):::tracker
        BL((Blender 3D - main DCC)):::app
        NAS[(Nas/FileSystem)]:::storage
        VCS[(VCS)]:::storage

        %% Invisible link to force the Title to stay at the very top of the layout
        Title ~~~ OSH

        %% Connections: Users to Hub
        TD_User -->|"Initial Conf/\nmaintenance"| OSH
        PM_User -->|"Monitors progress/\nGenerates files"| OSH
        ED_User -->|"Sees assigned\ntimeline / edits"| OSH
        AR_User -->|"Sees assigned tasks/\nworks"| OSH
    
        %% Direct connections: Manual / Current workflows (Dashed)
        PM_User -.->|"Manual Script Breakdown (Current)"| Kitsu
        TD_User -.->|"Sets up Studio/\nTeam"| Kitsu

        %% Connections: OpenStudioHub outwards
        OSH <-->|"Gets and sets\nProd status and actors"| Kitsu
        OSH -->|"Configures and Launches\nfor monitoring"| WT
        OSH -->|"Launches appropriate\nfiles for tasks/users"| BL
        OSH -->|"Manages topography\nCreates and deletes files"| NAS
        OSH -->|"Sets up project repos."| VCS

        %% Connections: Blender interactions
        BL -->|"Updates task progress"| Kitsu
        BL -->|"Saves playblasts"| NAS
        BL -->|"Generates and Updates\n.blend working files"| VCS

        %% Connections: WatchTower interactions
        WT -->|"Gets productions"| Kitsu
    end

    style SystemContainer fill:#222222,stroke:#0c0c0c,stroke-width:3px,color:#1e1e1e,stroke-dasharray: 5 5
```

---

## 💻 Development & Installation

The codebase is designed following the **Separation of Concerns (MVC)** principle, making it highly maintainable for Enterprise scaling.

1. Clone the repository:

```bash
git clone [https://github.com/tu-usuario/openstudio-hub.git](https://github.com/tu-usuario/openstudiohub.git)
cd openstudiohub

```

2. Create and activate the virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows

```

3. Install dependencies:

```bash
pip install -r requirements.txt

```

4. Run the Hub:

```bash
python openstudiohub.py

```

## 📦 Packaging for Production

To distribute the tool to studio artists without requiring them to install Python, the application is "frozen" into a standalone executable using PyInstaller.

```bash
pyinstaller --noconsole --onefile --name "OpenStudioHub" openstudiohub.py

```

*(Note: The compiled executable is not tracked in this repository. Please visit the **Releases** tab to download the latest production build).*

---

*Developed by Ernesto Del Valle M. - Pipeline TD & Technical Artist.*
