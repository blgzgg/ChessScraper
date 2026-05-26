from flask import Flask, request, send_file, jsonify, Response, stream_with_context
import io
import json
import queue
import threading
import datetime
from scraper import find_all_game_data
from flask_cors import CORS
import db

import plotly.graph_objects as go

app = Flask(__name__)
CORS(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result_label(victory) -> str:
    if victory == 1:
        return "Win"
    if victory == 0:
        return "Loss"
    if victory == -1:
        return "Draw"
    return "Unknown"


def _fmt_date(epoch) -> str:
    """Convert a Unix timestamp to a readable date/time string."""
    if not epoch:
        return "Unknown"
    try:
        return datetime.datetime.utcfromtimestamp(int(epoch)).strftime("%Y-%m-%d  %H:%M UTC")
    except Exception:
        return str(epoch)



# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------



@app.route("/generate_plotly_graph", methods=["POST"])
def plotly_graph():
    data = request.get_json()
    username = data.get("username", "").lower().strip()
    if not username:
        return jsonify({"error": "No username provided"}), 400

    games_list = find_all_game_data(username)
    games_list = _apply_filters(games_list, data)
    fig = _build_metric_figure(games_list, username, metric="kdr")
    return Response(_render_figure(fig), mimetype='text/html')


@app.route("/generate_weighted_plotly_graph", methods=["POST"])
def weighted_plotly_graph():
    data = request.get_json()
    username = data.get("username", "").lower().strip()
    if not username:
        return jsonify({"error": "No username provided"}), 400

    games_list = find_all_game_data(username)
    games_list = _apply_filters(games_list, data)
    fig = _build_metric_figure(games_list, username, metric="weighted_kdr")
    return Response(_render_figure(fig), mimetype='text/html')


@app.route("/generate_survival_plotly_graph", methods=["POST"])
def survival_plotly_graph():
    data = request.get_json()
    username = data.get("username", "").lower().strip()
    if not username:
        return jsonify({"error": "No username provided"}), 400

    games_list = find_all_game_data(username)
    games_list = _apply_filters(games_list, data)
    fig = _build_metric_figure(games_list, username, metric="survival_rate")
    return Response(_render_figure(fig), mimetype='text/html')


def _apply_filters(games_list, data):
    """Apply optional filters from the request body.

    Recognized fields in `data`:
      - date_from:  ISO date string "YYYY-MM-DD" (inclusive lower bound)
      - date_to:    ISO date string "YYYY-MM-DD" (inclusive upper bound — end of day)
      - opponent:   case-insensitive substring match against opponent username
      - result:     'win' | 'loss' | 'draw'  (filters by Game.victory: 1/0/-1)
      - color:      'white' | 'black'         (filters by user-color)

    Empty / missing filters are simply skipped. The filtered list preserves
    the original chronological order so game numbering in the tooltip
    reflects the filtered view ("Game 1" = first game shown after filtering).
    """
    if not data:
        return games_list

    date_from = (data.get("date_from") or "").strip()
    date_to   = (data.get("date_to")   or "").strip()
    opponent  = (data.get("opponent")  or "").strip().lower()
    result    = (data.get("result")    or "").strip().lower()
    color     = (data.get("color")     or "").strip().lower()

    if not (date_from or date_to or opponent or result or color):
        return games_list  # fast path: nothing to filter

    # Map the result filter values to Game.victory codes
    result_to_victory = {"win": 1, "loss": 0, "draw": -1}
    victory_target = result_to_victory.get(result)

    # Parse the date bounds once, treating them as UTC midnight (lower) and
    # end-of-day (upper) so both endpoints feel inclusive to the user.
    epoch_from = None
    epoch_to   = None
    if date_from:
        try:
            dt = datetime.datetime.strptime(date_from, "%Y-%m-%d")
            epoch_from = int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.datetime.strptime(date_to, "%Y-%m-%d")
            dt = dt.replace(hour=23, minute=59, second=59, tzinfo=datetime.timezone.utc)
            epoch_to = int(dt.timestamp())
        except ValueError:
            pass

    def keep(g):
        raw = g.get_format("raw") or {}
        epoch = raw.get("end_time") or g.get_format("date") or 0
        if epoch_from is not None and epoch < epoch_from: return False
        if epoch_to   is not None and epoch > epoch_to:   return False
        if opponent:
            opp = (g.get_format("opponent") or "").lower()
            if opponent not in opp: return False
        if victory_target is not None:
            if g.get_format("victory") != victory_target: return False
        if color:
            game_color = (g.get_format("color") or "").lower()
            if game_color != color: return False
        return True

    return [g for g in games_list if keep(g)]


# JS injected after plotly renders the chart. Clicking a data point opens
# the corresponding chess.com game in a new tab. URLs in customdata[9] are
# stored without the common prefix to save DB space; we re-add it here.
_GAME_URL_PREFIX = "https://www.chess.com/game/"

_CLICK_HANDLER_JS = r"""
(function() {
    var graphDiv = document.querySelector('.plotly-graph-div');
    if (!graphDiv) return;
    graphDiv.style.cursor = 'pointer';

    var URL_PREFIX = '__URL_PREFIX__';

    graphDiv.on('plotly_click', function(eventData) {
        if (!eventData || !eventData.points || !eventData.points.length) return;
        var pt = eventData.points[0];
        if (pt.curveNumber !== 0) return;          // ignore baseline trace
        if (!pt.customdata || pt.customdata.length < 10) return;
        var suffix = pt.customdata[9];
        if (suffix) window.open(URL_PREFIX + suffix, '_blank', 'noopener');
    });
})();
""".replace("__URL_PREFIX__", _GAME_URL_PREFIX)



def _render_figure(fig) -> str:
    """Render a Plotly figure to a self-contained HTML string with a custom
    click handler that pins a clickable tooltip when a data point is clicked.
    """
    html = fig.to_html(
        include_plotlyjs='cdn',
        full_html=True,
        post_script=_CLICK_HANDLER_JS,
    )
    # Inject a tiny CSS rule so the body matches our card aesthetic when the
    # iframe-rendered HTML is viewed standalone.
    style_tag = (
        "<style>body{margin:0;background-color:#262421;}"
        ".plotly-graph-div{cursor:pointer;}</style>"
    )
    return html.replace("</head>", style_tag + "</head>", 1)


def _build_metric_figure(games_list, username, *, metric="kdr"):
    """Build a Plotly figure for a per-game time-series metric.

    Supported metrics:
      - 'kdr'             — kills / deaths
      - 'weighted_kdr'    — weighted kills / weighted deaths (Q=9, R=5, B=3, N=3, P=1)
      - 'survival_rate'   — (16 - deaths) / 16, expressed as a percentage
    """
    # Per-metric configuration: which field to plot, axis labels, baseline, etc.
    if metric == "weighted_kdr":
        value_field = "weighted_kdr"
        kills_field, deaths_field = "weighted_kills", "weighted_deaths"
        title = f"Weighted KDR over time — {username}"
        y_axis_title = "Weighted Kill / Death Ratio"
        trace_name = "Weighted Kill/Death Ratio"
        value_label = "Weighted KDR"
        kills_label = "Weighted Kills"
        deaths_label = "Weighted Deaths"
        line_color = "#c9a23c"          # gold
        show_baseline = True
        baseline_value = 1.0
        baseline_label = "Baseline (1.0)"
        y_format = ".2f"
        y_tickformat = None              # default Plotly numeric formatting
    elif metric == "survival_rate":
        value_field = None               # computed inline below
        kills_field, deaths_field = "kills", "deaths"
        title = f"Piece Survival Rate per Game — {username}"
        y_axis_title = "Surviving Pieces (% of 16)"
        trace_name = "Survival Rate"
        value_label = "Survival"
        kills_label = "Kills"
        deaths_label = "Deaths"
        line_color = "#3aa3c9"          # cool blue, distinct from green/gold
        show_baseline = False
        baseline_value = None
        baseline_label = None
        y_format = ".0%"                 # tooltip: "87%"
        y_tickformat = ".0%"             # axis ticks: "0%, 25%, 50%, 75%, 100%"
    else:  # default: kdr
        value_field = "kdr"
        kills_field, deaths_field = "kills", "deaths"
        title = f"KDR over time — {username}"
        y_axis_title = "Kill / Death Ratio"
        trace_name = "Kill/Death Ratio"
        value_label = "KDR"
        kills_label = "Kills"
        deaths_label = "Deaths"
        line_color = "#5d9948"          # primary green
        show_baseline = True
        baseline_value = 1.0
        baseline_label = "Baseline (1.0)"
        y_format = ".2f"
        y_tickformat = None

    # Empty result (e.g. filters matched no games) — show a friendly placeholder
    # rather than crashing on the indexing below.
    if not games_list:
        fig = go.Figure()
        fig.update_layout(
            title=dict(
                text=title,
                font=dict(size=18, color='#ffffff', family='Arial, sans-serif'),
                x=0.5, xanchor='center', y=0.96,
            ),
            paper_bgcolor='#262421',
            plot_bgcolor='#1a1816',
            font=dict(color='#d9d6d2', family='Arial, sans-serif'),
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            annotations=[dict(
                text="No games match the current filters",
                xref="paper", yref="paper",
                x=0.5, y=0.5,
                showarrow=False,
                font=dict(size=16, color='#b8b6b3'),
            )],
            margin=dict(l=70, r=30, t=70, b=70),
        )
        return fig

    # Compute the y-values. KDR variants read directly from a Game field;
    # survival rate is derived from kills/deaths in real time so we don't need
    # a stored field for it.
    if metric == "survival_rate":
        y_values = [
            (16 - (game.get_format("deaths") or 0)) / 16
            for game in games_list
        ]
    else:
        y_values = [game.get_format(value_field) or 0 for game in games_list]

    # X-coordinates are evenly-spaced game indices for readability.
    # Date strings become the tick labels via xaxis.tickvals/ticktext below.
    x_indices = list(range(1, len(games_list) + 1))

    # Pre-format each game's date for both the tick labels and the tooltip
    game_date_labels = []
    for game in games_list:
        raw = game.get_format("raw") or {}
        epoch = raw.get("end_time") or game.get_format("date") or 0
        try:
            dt = datetime.datetime.utcfromtimestamp(int(epoch))
            game_date_labels.append(dt.strftime("%b %d, %Y"))
        except (ValueError, TypeError, OSError):
            game_date_labels.append("")

    # Pick a reasonable subset of ticks so the axis stays readable on long timelines.
    n = len(games_list)
    target_ticks = min(10, n)
    if target_ticks > 1:
        step = max(1, (n - 1) // (target_ticks - 1))
        tick_positions = list(range(1, n + 1, step))
        if tick_positions[-1] != n:
            tick_positions.append(n)
    else:
        tick_positions = x_indices[:]

    tick_labels = [game_date_labels[i - 1] for i in tick_positions]

    # ------------------------------------------------------------------
    # Build per-point hover data
    # Order: [date_str, kills, deaths, opponent, opp_elo, user_elo, color, result, game_num, url]
    # ------------------------------------------------------------------
    customdata = []
    for i, game in enumerate(games_list):
        raw      = game.get_format("raw") or {}
        date_str = _fmt_date(raw.get("end_time") or game.get_format("date"))
        kills    = game.get_format(kills_field)  or 0
        deaths   = game.get_format(deaths_field) or 0

        opponent    = game.get_format("opponent")
        opp_elo     = game.get_format("opponent_elo")
        user_elo    = game.get_format("user_elo")
        color       = game.get_format("color")
        victory_val = game.get_format("victory")

        # Strip the common chess.com prefix if present (handles fresh API
        # data which has the full URL); cached DB data is already suffix-only.
        url_field = raw.get("url") or ""
        if url_field.startswith(_GAME_URL_PREFIX):
            url_field = url_field[len(_GAME_URL_PREFIX):]

        opponent = opponent if opponent is not None else "Unknown"
        opp_elo  = opp_elo  if opp_elo  is not None else "N/A"
        user_elo = user_elo if user_elo  is not None else "N/A"
        color    = (color if color is not None else "Unknown").capitalize()
        result   = _result_label(victory_val)

        customdata.append([
            date_str, kills, deaths, opponent, opp_elo,
            user_elo, color, result, i + 1, url_field,
        ])

    hover_template = (
        "<b>Game %{customdata[8]}  ·  %{customdata[0]}</b><br>"
        "──────────────────────────<br>"
        f"• {value_label}: <b>%{{y:{y_format}}}</b><br>"
        f"• {kills_label}: <b>%{{customdata[1]}}</b><br>"
        f"• {deaths_label}: <b>%{{customdata[2]}}</b><br>"
        "• Opponent: <b>%{customdata[3]}</b>  (ELO %{customdata[4]})<br>"
        "• Your ELO: <b>%{customdata[5]}</b><br>"
        "• Playing as: <b>%{customdata[6]}</b><br>"
        "• Result: <b>%{customdata[7]}</b><br>"
        "<span style='color:#5d9948'>↗ Click point to open game on Chess.com</span>"
        "<extra></extra>"
    )

    # Colour dots by result: green=win, red=loss, grey=draw
    result_color_map = {"Win": "#4caf50", "Loss": "#f44336", "Draw": "#9e9e9e"}
    marker_colors = [result_color_map.get(cd[7], "#9e9e9e") for cd in customdata]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=x_indices, y=y_values,
        mode='lines+markers',
        name=trace_name,
        customdata=customdata,
        hovertemplate=hover_template,
        line=dict(color=line_color, width=2),
        marker=dict(color=marker_colors, size=9,
                    line=dict(color='white', width=1.5)),
    ))

    if show_baseline:
        fig.add_trace(go.Scatter(
            x=x_indices, y=[baseline_value] * len(games_list),
            mode='lines',
            name=baseline_label,
            line=dict(dash='dash', color='#aaaaaa', width=1.5),
            hoverinfo='skip',
        ))

    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=18, color='#ffffff', family='Arial, sans-serif'),
            x=0.5,
            xanchor='center',
            y=0.96,
        ),
        xaxis_title=dict(
            text="Date",
            font=dict(size=13, color='#b8b6b3'),
        ),
        yaxis_title=dict(
            text=y_axis_title,
            font=dict(size=13, color='#b8b6b3'),
        ),
        plot_bgcolor='#1a1816',
        paper_bgcolor='#262421',
        font=dict(color='#d9d6d2', family='Arial, sans-serif'),
        hoverlabel=dict(
            bgcolor='#1e1e1e',
            bordercolor=line_color,
            font=dict(color='#ffffff', size=12, family='Arial, sans-serif'),
            align='left',
        ),
        legend=dict(
            bgcolor='rgba(38, 36, 33, 0.85)',
            bordercolor='#3d3a36',
            borderwidth=1,
            font=dict(size=11),
            x=0.99, y=0.99,
            xanchor='right',
            yanchor='top',
        ),
        xaxis=dict(
            gridcolor='#2e2b28',
            zerolinecolor='#3d3a36',
            tickmode='array',
            tickvals=tick_positions,
            ticktext=tick_labels,
            tickangle=-30,
            tickfont=dict(size=10, color='#b8b6b3'),
        ),
        yaxis=dict(
            gridcolor='#2e2b28',
            zerolinecolor='#3d3a36',
            tickfont=dict(size=10, color='#b8b6b3'),
            tickformat=y_tickformat,
            # For survival rate, lock the range to [0, 1] so the y-axis
            # reads as a percentage of all 16 pieces — otherwise Plotly
            # auto-zooms which makes "92% vs 95%" look like a huge gap.
            range=[0, 1.02] if metric == "survival_rate" else None,
        ),
        hovermode='closest',
        margin=dict(l=70, r=30, t=70, b=70),
    )

    return fig


def main():
    app.run(debug=True, threaded=True)


@app.route("/parse_progress", methods=["GET"])
def parse_progress():
    """
    Server-Sent Events stream that runs find_all_game_data on a background
    thread and forwards every progress callback to the browser.

    The frontend opens this with EventSource('/parse_progress?username=...')
    and listens for 'progress' and 'done' events. After 'done' fires it
    fetches the graph + stats from the existing endpoints.

    Note: SSE is GET-only by spec, so the username arrives via query string.
    """
    username = (request.args.get("username") or "").lower().strip()
    if not username:
        return jsonify({"error": "No username provided"}), 400

    events = queue.Queue()
    SENTINEL = object()  # signals the worker is finished

    def progress_callback(stage, current, total, **extra):
        events.put({
            "stage":   stage,
            "current": current,
            "total":   total,
            **extra,
        })

    def worker():
        try:
            find_all_game_data(username, progress_callback=progress_callback)
        except Exception as exc:
            events.put({"stage": "error", "current": 0, "total": 0,
                        "message": str(exc)})
        finally:
            events.put(SENTINEL)

    threading.Thread(target=worker, daemon=True).start()

    @stream_with_context
    def event_stream():
        while True:
            payload = events.get()
            if payload is SENTINEL:
                break
            event_name = "done" if payload.get("stage") == "done" else \
                         "error" if payload.get("stage") == "error" else \
                         "progress"
            yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"

    return Response(event_stream(),
                    mimetype="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",  # disable proxy buffering
                    })


@app.route("/player_stats", methods=["POST"])
def player_stats():
    """
    Return the cached Player-row stats for the overview card.

    Assumes find_all_game_data has been called for this user at least once
    (which the front end does via /generate_plotly_graph). That call refreshes
    the avatar URL and aggregate stats in the DB.
    """
    data = request.get_json()
    username = data.get("username", "").lower().strip()
    if not username:
        return jsonify({"error": "No username provided"}), 400

    player = db.get_player(username)
    if not player:
        return jsonify({"error": f"Player '{username}' not found"}), 404

    return jsonify({
        "name":                    player.get("name", ""),
        "profile_pic_url":         player.get("profile-pic-url", ""),
        "profile_url":             f"https://www.chess.com/member/{player.get('name', '')}",
        "total_captures":          player.get("total-captures", 0),
        "total_deaths":            player.get("total-deaths", 0),
        "total_games":             player.get("total-games", 0),
        "current_kdr":             player.get("current-kdr", 0),
        "current_elo":             player.get("current-elo", 0),
        "total_weighted_captures": player.get("total-weighted-captures", 0),
        "total_weighted_deaths":   player.get("total-weighted-deaths", 0),
        "weighted_kdr":            player.get("weighted-kdr", 0),
    })


@app.route("/piece_stats", methods=["POST"])
def piece_stats():
    """
    Return aggregated per-piece stats for a player. The frontend uses this to
    populate the chess-board visualization where hovering over a piece shows
    its lifetime stats.
    """
    data = request.get_json()
    username = data.get("username", "").lower().strip()
    if not username:
        return jsonify({"error": "No username provided"}), 400

    rows = db.get_piece_stats_aggregate(username)
    # Convert to a piece-id → stats dict for easier lookup on the frontend
    by_piece = {row["piece_id"]: row for row in rows}

    return jsonify({
        "username":   username,
        "piece_stats": by_piece,
    })


@app.route("/opponents", methods=["POST"])
def opponents():
    """Return the list of opponents the player has faced, sorted by frequency.

    Accepts the same filter fields as the graph endpoints (date_from, date_to,
    result, color) and returns only opponents matching those filters. The
    opponent filter itself is excluded so users can browse alternatives.
    """
    data = request.get_json() or {}
    username = data.get("username", "").lower().strip()
    if not username:
        return jsonify({"error": "No username provided"}), 400

    # Translate the same filter fields the graph endpoints use into the
    # parameters get_opponents expects. Keep the parsing identical so the
    # autocomplete results always agree with the graph.
    date_from = (data.get("date_from") or "").strip()
    date_to   = (data.get("date_to")   or "").strip()
    result    = (data.get("result")    or "").strip().lower()
    color     = (data.get("color")     or "").strip().lower()

    epoch_from = None
    epoch_to   = None
    if date_from:
        try:
            dt = datetime.datetime.strptime(date_from, "%Y-%m-%d")
            epoch_from = int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.datetime.strptime(date_to, "%Y-%m-%d")
            dt = dt.replace(hour=23, minute=59, second=59, tzinfo=datetime.timezone.utc)
            epoch_to = int(dt.timestamp())
        except ValueError:
            pass

    result_to_victory = {"win": 1, "loss": 0, "draw": -1}
    victory = result_to_victory.get(result)

    rows = db.get_opponents(
        username,
        limit=200,
        date_from_epoch=epoch_from,
        date_to_epoch=epoch_to,
        victory=victory,
        color=(color if color in ("white", "black") else None),
    )
    return jsonify({"opponents": rows})


if __name__ == "__main__":
    main()