"""HTML-only synchronization for separate Plotly charts and subplot axes."""


def shared_xaxis_script(plot_count: int) -> str:
    """Register each chart after Plotly renders it; initialize once all are ready.

    Plotly replaces {plot_id} in post_script with the generated div ID.
    Cursor tables do not receive this script and are therefore excluded.
    """
    return r"""
(function () {
    const charts = window.mtbSharedXaxisCharts = window.mtbSharedXaxisCharts || [];
    charts.push(document.getElementById('{plot_id}'));
    if (charts.length !== PLOT_COUNT) return;

    const entries = charts.map(chart => ({
        chart,
        axes: Object.keys(chart.layout).filter(key => /^xaxis\d*$/.test(key))
    }));
    // Use the union of the rendered ranges so every signal is initially visible.
    const ranges = entries.flatMap(({chart, axes}) =>
        axes.map(axis => chart.layout[axis].range)
    ).filter(range => Array.isArray(range) && range.every(Number.isFinite));
    if (!ranges.length) return;
    const fullRange = [
        Math.min(...ranges.map(range => range[0])),
        Math.max(...ranges.map(range => range[1]))
    ];
    let updating = false;

    async function synchronize(range) {
        // Relayout emits another event. Hold this guard until all updates finish.
        updating = true;
        try {
            await Promise.all(entries.map(({chart, axes}) => {
                const update = {};
                axes.forEach(axis => {
                    update[axis + '.range'] = range.slice();
                    update[axis + '.autorange'] = false;
                });
                return Plotly.relayout(chart, update);
            }));
        } finally {
            updating = false;
        }
    }

    entries.forEach(({chart, axes}) => {
        chart.on('plotly_relayout', event => {
            if (updating) return;
            for (const axis of axes) {
                if (event[axis + '.autorange'] === true) {
                    return synchronize(fullRange);
                }
                if (event[axis + '.range'] !== undefined ||
                    event[axis + '.range[0]'] !== undefined ||
                    event[axis + '.range[1]'] !== undefined) {
                    return synchronize(chart.layout[axis].range);
                }
            }
        });
    });
    synchronize(fullRange);
})();
""".replace('PLOT_COUNT', str(plot_count))
