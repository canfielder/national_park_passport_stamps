# 🏞️ National Parks Tracker

A Streamlit-based application to track **National Park visits** and **National Park Passport Book stamps**. Keep track of which parks you and your family have visited and which annual stamps have been collected or remain.

---

## 📦 Project Structure

```
├── README.md
├── app/
│   └── app.py                # Main Streamlit application
├── config/
│   └── colors.json           # Color and theme configuration
├── data/
│   ├── manual_tracking/      # Raw CSVs for visits and stamps
│   ├── processed/            # Processed or aggregated data
│   └── raw/                  # Original source data (KML/KMZ, CSVs)
├── notebooks/                # Optional analysis notebooks
├── src/
│   └── national_parks/       # Python package source
│       └── common/
│           └── find_project_root.py
├── Makefile                  # Common developer commands
├── pyproject.toml            # Project metadata & dependencies
└── uv.lock                   # Locked dependency versions
```

---

## ⚙️ Setup & Installation

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/national_parks.git
cd national_parks
```

### 2. Create and activate the virtual environment
```bash
uv venv
source .venv/bin/activate
```

### 3. Install dependencies
```bash
uv sync --all-extras
```

---

## 🚀 Usage

### Launch the app
```bash
make launch
```
Open your browser at:
```
http://localhost:8501
```

### Lint and format code
```bash
make lint     # Run Ruff for linting
make format   # Format code using Black
```

### Sync or update dependencies
```bash
make sync
```

### Clean build artifacts
```bash
make clean
```

---

## 🧰 Developer Notes

- **Python version:** 3.11.4  
- **Package manager:** [uv](https://docs.astral.sh/uv)  
- **Linting:** [Ruff](https://docs.astral.sh/ruff)  
- **Formatting:** [Black](https://black.readthedocs.io/en/stable/)  
- **App framework:** [Streamlit](https://streamlit.io)  
- **Map visualization:** [Folium](https://python-visualization.github.io/folium/) and [streamlit-folium](https://pypi.org/project/streamlit-folium/)

---

## 🗺️ App Features

### 1. Track National Park Visits
- Log visits for **Evan** and **Kelsey**.  
- Visualize visited parks on a map.  
- Keep historical records of park visits.  

### 2. Track National Park Passport Book Stamps
- Track which **annual stamp locations** have been collected.  
- Visualize remaining stamps needed for the year.  
- Combine stamp data with visit history to quickly see what’s missing.  

---

## 🤝 Contributing

1. Create a new branch from `main`.  
2. Make changes and ensure linting passes:
```bash
make lint && make format
```
3. Commit, push, and open a pull request.

---

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for details.

