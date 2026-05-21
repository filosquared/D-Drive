let currentFilePath = null;
let currentSaveDir = null;
let selectedChannel = null;
let logIndex = 0;

// Chart.js Configuration
const ctx = document.getElementById('speedChart').getContext('2d');
const speedChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [{
            label: 'Speed (MB/s)',
            data: [],
            borderColor: '#5865f2',
            backgroundColor: 'rgba(88, 101, 242, 0.2)',
            tension: 0.4,
            fill: true
        }]
    },
    options: {
        responsive: true,
        scales: {
            x: {
                display: false
            },
            y: {
                beginAtZero: true,
                title: { display: true, text: 'MB/s' }
            }
        },
        animation: {
            duration: 0 // Disable animation for smoother real-time updates
        }
    }
});

// Tabs
function openTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));

    document.getElementById(tabName).classList.add('active');
    event.currentTarget.classList.add('active');
}

// Upload Logic
document.getElementById('select-file-btn').addEventListener('click', async () => {
    const res = await fetch('/api/select_file');
    const data = await res.json();
    if (data.path) {
        currentFilePath = data.path;
        document.getElementById('selected-file-label').innerText = data.path.split('/').pop(); // Show basename
        document.getElementById('upload-btn').disabled = false;
    }
});

document.getElementById('upload-btn').addEventListener('click', async () => {
    if (!currentFilePath) return;

    document.getElementById('upload-btn').disabled = true;
    const res = await fetch('/api/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: currentFilePath })
    });
    const data = await res.json();
    // Logs will handle status updates
});

// Download Logic
document.getElementById('scan-btn').addEventListener('click', async () => {
    const res = await fetch('/api/scan', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
        pollChannels();
    }
});

async function pollChannels() {
    const res = await fetch('/api/channels');
    const data = await res.json();
    const list = document.getElementById('channel-list');

    if (data.channels.length > 0) {
        list.innerHTML = '';
        data.channels.forEach(channel => {
            const li = document.createElement('li');
            li.textContent = channel;
            li.onclick = () => selectChannel(li, channel);
            list.appendChild(li);
        });
    }
}

function selectChannel(element, channelName) {
    document.querySelectorAll('li').forEach(el => el.classList.remove('selected'));
    element.classList.add('selected');
    selectedChannel = channelName;
    checkDownloadReady();
}

document.getElementById('select-folder-btn').addEventListener('click', async () => {
    const res = await fetch('/api/select_folder');
    const data = await res.json();
    if (data.path) {
        currentSaveDir = data.path;
        document.getElementById('selected-folder-label').innerText = data.path;
        checkDownloadReady();
    }
});

function checkDownloadReady() {
    if (selectedChannel && currentSaveDir) {
        document.getElementById('download-btn').disabled = false;
    }
}

document.getElementById('download-btn').addEventListener('click', async () => {
    if (!selectedChannel || !currentSaveDir) return;

    document.getElementById('download-btn').disabled = true;
    await fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel: selectedChannel, save_dir: currentSaveDir })
    });
});

// Logging System
async function pollLogs() {
    try {
        const res = await fetch(`/api/logs?start=${logIndex}`);
        const data = await res.json();

        if (data.logs.length > 0) {
            const consoleDiv = document.getElementById('log-console');
            data.logs.forEach(log => {
                const div = document.createElement('div');
                div.className = 'log-entry';
                div.textContent = log;
                consoleDiv.appendChild(div);
            });
            consoleDiv.scrollTop = consoleDiv.scrollHeight;
            logIndex = data.next_index;
        }
    } catch (e) {
        console.error("Log poll error", e);
    }
    setTimeout(pollLogs, 1000);
}

// Speed Polling
async function pollSpeed() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();

        // Update Chart
        const now = new Date();
        const speedMBs = (data.current_speed / (1024 * 1024)).toFixed(2);

        if (data.current_speed > 0 || speedChart.data.datasets[0].data.length > 0 && speedChart.data.datasets[0].data[speedChart.data.datasets[0].data.length - 1] > 0) {
            // Keep roughly 60 seconds history in chart
            if (speedChart.data.labels.length > 60) {
                speedChart.data.labels.shift();
                speedChart.data.datasets[0].data.shift();
            }

            speedChart.data.labels.push(now.toLocaleTimeString());
            speedChart.data.datasets[0].data.push(speedMBs);
            speedChart.update();
        }

    } catch (e) {
        console.error("Speed poll error", e);
    }
    setTimeout(pollSpeed, 1000);
}

// Start polling
pollLogs();
pollSpeed();
