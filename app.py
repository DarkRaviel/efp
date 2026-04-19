import math
import time
import os
import threading
from collections import defaultdict

from flask import Flask, jsonify, render_template_string
from flask_socketio import SocketIO

# -----------------------------
# LOAD DATA
# -----------------------------
def load_final_rank(file_path):
    final_rank = {}
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rank, team = line.strip().split(". ", 1)
                final_rank[team] = int(rank)
    return final_rank


def load_submissions(file_path):
    users = {}
    current_user = None

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if line.startswith("Ranking from:"):
                name = line.replace("Ranking from:", "").strip()

                base = name
                i = 1
                while name in users:
                    i += 1
                    name = f"{base} ({i})"

                current_user = name
                users[current_user] = {}

            elif line.startswith("---"):
                current_user = None

            elif current_user and line:
                rank, team = line.split(". ", 1)
                users[current_user][team] = int(rank)

    return users


# -----------------------------
# ANALYSIS
# -----------------------------
def analyze(final_rank, submissions):
    results = []
    team_errors = defaultdict(list)
    team_bias = defaultdict(list)
    user_details = {}

    for user, preds in submissions.items():
        penalty = 0
        exact = 0

        user_details[user] = []

        for team, final_pos in final_rank.items():
            user_pos = preds.get(team)
            if user_pos is None:
                continue

            diff = abs(final_pos - user_pos)
            penalty += diff

            team_errors[team].append(diff)
            team_bias[team].append(user_pos - final_pos)

            user_details[user].append({
                "team": team,
                "pred": user_pos,
                "actual": final_pos,
                "diff": diff
            })

            if diff == 0:
                exact += 1

        results.append({
            "user": user,
            "penalty": penalty,
            "exact": exact
        })

    return results, team_errors, team_bias, user_details


# -----------------------------
# STATS
# -----------------------------
def compute_stats(team_errors, team_bias):
    stats = {}

    for team in team_errors:
        errors = team_errors[team]
        bias_list = team_bias[team]

        stats[team] = {
            "avg_error": sum(errors) / len(errors),
            "bias": sum(bias_list) / len(bias_list)
        }

    return stats


def sort_results(results):
    return sorted(results, key=lambda x: (x["penalty"], -x["exact"]))


# -----------------------------
# INIT DATA
# -----------------------------
final_rank = load_final_rank("final_rank.txt")
submissions = load_submissions("submissions.txt")

results, team_errors, team_bias, user_details = analyze(final_rank, submissions)
results = sort_results(results)

stats = compute_stats(team_errors, team_bias)


# -----------------------------
# FLASK + SOCKETIO
# -----------------------------
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


# -----------------------------
# HTML DASHBOARD
# -----------------------------
HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Pro Analytics Dashboard</title>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>

<style>
body {
    font-family: Arial;
    margin: 20px;
    background: #111;
    color: white;
}

.light { background: white; color: black; }

canvas { max-width: 800px; margin-top: 25px; }

input {
    padding: 6px;
    margin-bottom: 10px;
}

table {
    width: 100%;
    border-collapse: collapse;
}

td, th {
    border: 1px solid #444;
    padding: 6px;
    text-align: center;
}

.highlight { color: #22C55E; font-weight: bold; }
</style>
</head>

<body>

<h1>📊 Pro Analytics Dashboard</h1>

<button onclick="toggleDark()">🌙 Toggle Mode</button>

<br><br>
<input type="text" id="search" placeholder="Search user..." oninput="filterUsers()">

<canvas id="leaderboardChart"></canvas>
<canvas id="teamErrorChart"></canvas>
<canvas id="teamBiasChart"></canvas>

<div id="insights"></div>
<div id="details"></div>

<script>

let socket = io();

let chart1, chart2, chart3;
let globalResults = [];

// -------------------------
function toggleDark() {
    document.body.classList.toggle("light");
}

// -------------------------
fetch("/api/results")
    .then(r => r.json())
    .then(data => {
        globalResults = data;
        renderAll(globalResults);
    });

// -------------------------
socket.on("update", (data) => {
    globalResults = data.results;
    renderAll(globalResults);
});

// -------------------------
function renderAll(results) {
    renderLeaderboard(results);
    renderTeamCharts();
    generateInsights(results);
}

// -------------------------
function renderLeaderboard(results) {

    if (!results.length) return;

    const ctx = document.getElementById("leaderboardChart");
    if (chart1) chart1.destroy();

    const bestPenalty = Math.min(...results.map(r => r.penalty));

    chart1 = new Chart(ctx, {
        type: "bar",
        data: {
            labels: results.map(r =>
                r.penalty === bestPenalty ? "🏅 " + r.user : r.user
            ),
            datasets: [{
                label: "Penalty",
                data: results.map(r => r.penalty || 0),
                backgroundColor: "#4F46E5",
                borderRadius: 8
            }]
        },
        options: {
            onClick: (evt, elements) => {
                if (elements.length) {
                    const i = elements[0].index;
                    loadUser(results[i].user);
                }
            }
        }
    });
}

// -------------------------
function renderTeamCharts() {
    fetch("/api/stats")
        .then(r => r.json())
        .then(stats => {

            const teams = Object.keys(stats);
            const values = Object.values(stats);

            if (chart2) chart2.destroy();
            chart2 = new Chart(document.getElementById("teamErrorChart"), {
                type: "bar",
                data: {
                    labels: teams,
                    datasets: [{
                        label: "Avg Error",
                        data: values.map(s => s.avg_error),
                        backgroundColor: "#22C55E"
                    }]
                }
            });

            if (chart3) chart3.destroy();
            chart3 = new Chart(document.getElementById("teamBiasChart"), {
                type: "bar",
                data: {
                    labels: teams,
                    datasets: [{
                        label: "Bias",
                        data: values.map(s => s.bias),
                        backgroundColor: values.map(s =>
                            s.bias < 0 ? "#3B82F6" : "#EF4444"
                        )
                    }]
                }
            });
        });
}

// -------------------------
function filterUsers() {
    const text = document.getElementById("search").value.toLowerCase();

    const filtered = globalResults.filter(r =>
        r.user.toLowerCase().includes(text)
    );

    renderLeaderboard(filtered);
}

// -------------------------
function loadUser(user) {
    fetch("/user/" + user)
        .then(r => r.json())
        .then(data => showUser(user, data));
}

// -------------------------
function showUser(user, data) {

    data.sort((a,b) => b.diff - a.diff);

    let html = `<h2>👤 ${user}</h2><table>`;
    html += "<tr><th>Team</th><th>Pred</th><th>Actual</th><th>Diff</th></tr>";

    data.forEach(d => {
        html += `
        <tr>
            <td>${d.team}</td>
            <td>${d.pred}</td>
            <td>${d.actual}</td>
            <td class="${d.diff === 0 ? 'highlight':''}">${d.diff}</td>
        </tr>`;
    });

    html += "</table>";

    document.getElementById("details").innerHTML = html;
}

// -------------------------
function generateInsights(results) {

    const best = results.reduce((a,b)=> a.penalty < b.penalty ? a : b);
    const worst = results.reduce((a,b)=> a.penalty > b.penalty ? a : b);

    let html = "<h3>🧠 Insights</h3>";
    html += `<p>🏆 Best predictor: <b>${best.user}</b></p>`;
    html += `<p>💀 Worst predictor: <b>${worst.user}</b></p>`;

    document.getElementById("insights").innerHTML = html;
}

</script>

</body>
</html>
"""


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/api/results")
def api_results():
    return jsonify(results)


@app.route("/api/stats")
def api_stats():
    return jsonify(stats)


@app.route("/user/<username>")
def user(username):
    return jsonify(user_details.get(username, []))


# -----------------------------
# WATCHER
# -----------------------------
def watcher():
    global results, stats, team_errors, team_bias, user_details

    last_mtime = 0

    while True:
        try:
            mtime = os.path.getmtime("submissions.txt")

            if mtime != last_mtime:
                last_mtime = mtime

                submissions = load_submissions("submissions.txt")

                results, team_errors, team_bias, user_details = analyze(final_rank, submissions)
                results = sort_results(results)

                stats = compute_stats(team_errors, team_bias)

                socketio.emit("update", {"results": results})

        except Exception as e:
            print("Watcher error:", e)

        time.sleep(2)


threading.Thread(target=watcher, daemon=True).start()


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=10000)