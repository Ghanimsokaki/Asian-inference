# Foundry Mobile

A self-contained phone-company management prototype with a 3D-style campus world and 2D management menus inspired by the arc of building a tech empire: start in a 2007 garage, hire staff, research daily, tune a custom CPU/GPU, build an office and lab, then unlock a factory.

## Run locally

From the repository root:

```bash
python -m http.server 8080 --directory game --bind 0.0.0.0
```

Then open `http://localhost:8080`.

## Game loop

- **End day** to pay burn, generate staff research points, and advance active research.
- **Research lab** is the gate for all advanced silicon: staff must research the dual-core CPU architecture, pocket graphics engine, memory controller, camera module, and precision assembly before those options appear in the phone studio.
- **Hire staff** from the research lab; each hire costs cash and produces research points every day.
- **Build campus** progresses from garage → office/lab/QA → factory; the dashboard renders the campus as an interactive 3D-style perspective world while all menus remain 2D.
- **Phone studio** lets you rename the phone and configure CPU, GPU, and finish/camera.
- **Launch prototype** spends cash to earn reputation and initial market share.
- Progress is saved automatically in browser `localStorage`.
