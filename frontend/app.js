/**
 * TradingBot V5 - Dashboard Application Logic
 */

document.addEventListener('DOMContentLoaded', () => {
    // State 
    const state = {
        equityHistory: [],
        equityLabels: [],
        chartInstance: null
    };

    // Elements
    const els = {
        statusDot: document.getElementById('health-dot'),
        statusText: document.getElementById('health-status'),
        uptimeBadge: document.getElementById('uptime-badge'),
        
        valEquity: document.getElementById('val-equity'),
        valHwm: document.getElementById('val-hwm'),
        valPnlDaily: document.getElementById('val-pnl-daily'),
        valTotalTrades: document.getElementById('val-total-trades'),
        valWinRate: document.getElementById('val-win-rate'),
        valDrawdown: document.getElementById('val-drawdown'),
        valSlippage: document.getElementById('val-slippage'),
        valFees: document.getElementById('val-fees'),
        
        positionsCount: document.getElementById('positions-count'),
        positionsTbody: document.getElementById('positions-tbody')
    };

    // Initialize Chart.js
    function initChart() {
        const ctx = document.getElementById('equityChart').getContext('2d');
        
        Chart.defaults.color = '#858595';
        Chart.defaults.font.family = "'Inter', sans-serif";
        
        const gradient = ctx.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, 'rgba(59, 130, 246, 0.4)');
        gradient.addColorStop(1, 'rgba(59, 130, 246, 0.0)');

        state.chartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: state.equityLabels,
                datasets: [{
                    label: 'Total Equity ($)',
                    data: state.equityHistory,
                    borderColor: '#3b82f6',
                    backgroundColor: gradient,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 6,
                    fill: true,
                    tension: 0.2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: 'rgba(22, 22, 26, 0.9)',
                        titleColor: '#fff',
                        bodyColor: '#fff',
                        borderColor: 'rgba(255,255,255,0.1)',
                        borderWidth: 1,
                        padding: 12
                    }
                },
                scales: {
                    x: {
                        grid: { display: false, drawBorder: false },
                        ticks: { maxTicksLimit: 8 }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
                        border: { dash: [4, 4] }
                    }
                },
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false
                }
            }
        });
    }

    // Formatters
    const formatCurrency = (val) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val || 0);
    const formatPercent = (val) => `${(val * 100).toFixed(2)}%`;
    const formatTime = (seconds) => {
        if (!seconds) return '--:--:--';
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    };

    // Update UI Elements
    function updateUI(healthData, metricsData, positionsData, equityData) {
        // Health
        if (healthData && healthData.status === 'running') {
            els.statusDot.className = 'status-dot pulsing online';
            els.statusText.textContent = 'System Online';
            els.statusText.style.color = 'var(--text-main)';
            els.uptimeBadge.textContent = `Uptime: ${formatTime(healthData.uptime_seconds)}`;
        } else {
            els.statusDot.className = 'status-dot pulsing offline';
            els.statusText.textContent = 'System Offline';
            els.statusText.style.color = 'var(--accent-red)';
            els.uptimeBadge.textContent = 'Uptime: --:--:--';
        }

        if(!metricsData || metricsData.error) return;

        // Main Metrics
        els.valEquity.textContent = formatCurrency(metricsData.equity);
        els.valHwm.textContent = formatCurrency(metricsData.high_water_mark);
        
        els.valPnlDaily.textContent = formatCurrency(metricsData.daily_pnl);
        els.valPnlDaily.className = `value ${metricsData.daily_pnl >= 0 ? 'positive' : 'negative'}`;
        // add + sign if positive
        if(metricsData.daily_pnl > 0) els.valPnlDaily.textContent = '+' + els.valPnlDaily.textContent;

        els.valTotalTrades.textContent = metricsData.total_trades;
        
        const winR = metricsData.total_trades > 0 ? (metricsData.winning_trades / metricsData.total_trades) : 0;
        els.valWinRate.textContent = formatPercent(winR);

        els.valDrawdown.textContent = formatPercent(metricsData.current_drawdown);
        els.valSlippage.textContent = formatCurrency(metricsData.total_slippage);
        els.valFees.textContent = formatCurrency(metricsData.total_fees);

        // Update Chart
        if (equityData && !equityData.error && state.chartInstance) {
            const timeStr = new Date(equityData.timestamp * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'});
            
            // Add new point
            state.equityLabels.push(timeStr);
            state.equityHistory.push(equityData.equity);
            
            // Keep last 100 points
            if(state.equityLabels.length > 100) {
                state.equityLabels.shift();
                state.equityHistory.shift();
            }
            
            state.chartInstance.update('none'); // Update without animation for smooth progressive drawing
        }

        // Positions List
        if (positionsData && !positionsData.error) {
            els.positionsCount.textContent = positionsData.count;
            
            if (positionsData.count === 0) {
                els.positionsTbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted)">No open positions</td></tr>`;
            } else {
                let html = '';
                positionsData.positions.forEach(pos => {
                    const sideClass = pos.side.toLowerCase() === 'long' ? 'long' : 'short';
                    const pnlClass = pos.unrealized_pnl >= 0 ? 'positive' : 'negative';
                    const pnlStr = pos.unrealized_pnl >= 0 ? `+${formatCurrency(pos.unrealized_pnl)}` : formatCurrency(pos.unrealized_pnl);
                    
                    html += `
                        <tr>
                            <td><strong>${pos.symbol}</strong></td>
                            <td><span class="side-badge ${sideClass}">${pos.side}</span></td>
                            <td>${pos.quantity.toFixed(4)}</td>
                            <td>${formatCurrency(pos.avg_entry_price)}</td>
                            <td class="pnl-cell ${pnlClass}">${pnlStr}</td>
                        </tr>
                    `;
                });
                els.positionsTbody.innerHTML = html;
            }
        }
    }

    // Fetch Data
    async function fetchData() {
        try {
            const [healthRes, metricsRes, posRes, eqRes] = await Promise.all([
                fetch('/health').catch(() => null),
                fetch('/metrics').catch(() => null),
                fetch('/positions').catch(() => null),
                fetch('/equity').catch(() => null)
            ]);

            const healthData = healthRes ? await healthRes.json() : null;
            const metricsData = metricsRes ? await metricsRes.json() : null;
            const posData = posRes ? await posRes.json() : null;
            const eqData = eqRes ? await eqRes.json() : null;

            updateUI(healthData, metricsData, posData, eqData);
        } catch (error) {
            console.error("Dashboard Fetch Error:", error);
            // On complete failure
            els.statusDot.className = 'status-dot pulsing offline';
            els.statusText.textContent = 'Connection Error';
            els.statusText.style.color = 'var(--accent-red)';
        }
    }

    // Boot
    initChart();
    fetchData(); // run immediately
    setInterval(fetchData, 3000); // Poll every 3 seconds
});
