const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const express = require('express');
const bodyParser = require('body-parser');
const cors = require('cors');

// --- Configuration ---
const WHITELIST_FILE = path.join(__dirname, 'whitelist.json');
const SETTINGS_FILE = path.join(__dirname, 'settings.json');
const PENDING_FILE = path.join(__dirname, 'pending.json');
const LLM_API_URL = 'http://localhost:8000/chat';
const TELEGRAM_NOTIFY_URL = 'http://localhost:8000/telegram/notify';
const API_PORT = 3000;

const DEFAULT_SETTINGS = {
    busyMode: false,
    autoSend: false,
    busyReplyTemplate: "I'm tied up right now but will get back to you soon.",
};

let clientReady = false;
let lastQr = null;
let lastQrAt = null;

// --- Express Server Setup ---
const app = express();
app.use(cors());
app.use(bodyParser.json());

// Load Whitelist
let whitelist = [];
try {
    if (fs.existsSync(WHITELIST_FILE)) {
        whitelist = JSON.parse(fs.readFileSync(WHITELIST_FILE, 'utf8'));
    } else {
        fs.writeFileSync(WHITELIST_FILE, JSON.stringify([], null, 2));
    }
} catch (err) {
    console.error("Error loading whitelist:", err);
}

function saveWhitelist() {
    fs.writeFileSync(WHITELIST_FILE, JSON.stringify(whitelist, null, 2));
}

function loadSettings() {
    try {
        if (fs.existsSync(SETTINGS_FILE)) {
            const data = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
            return { ...DEFAULT_SETTINGS, ...(data || {}) };
        }
        saveSettings(DEFAULT_SETTINGS);
    } catch (err) {
        console.error("Error loading settings:", err);
    }
    return { ...DEFAULT_SETTINGS };
}

function saveSettings(settings) {
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2));
}

function loadPending() {
    try {
        if (fs.existsSync(PENDING_FILE)) {
            const data = JSON.parse(fs.readFileSync(PENDING_FILE, 'utf8'));
            return Array.isArray(data) ? data : [];
        }
        savePending([]);
    } catch (err) {
        console.error("Error loading pending:", err);
    }
    return [];
}

function savePending(pending) {
    fs.writeFileSync(PENDING_FILE, JSON.stringify(pending, null, 2));
}

function createPending({ fromId, fromName, message, draft }) {
    const pending = loadPending();
    const rawId = crypto.randomUUID ? crypto.randomUUID() : crypto.randomBytes(16).toString('hex');
    const id = `wa_${rawId}`;
    pending.push({
        id,
        from_id: fromId,
        from_name: fromName,
        message,
        draft,
        status: "pending",
        created_at: new Date().toISOString()
    });
    savePending(pending);
    return id;
}

async function notifyTelegram(message) {
    try {
        await axios.post(TELEGRAM_NOTIFY_URL, { message });
    } catch (err) {
        console.error("Failed to notify Telegram:", err.message);
    }
}

const CHROME_PATH = process.env.CHROME_PATH || process.env.PUPPETEER_EXECUTABLE_PATH;

// Initialize the WhatsApp client
const client = new Client({
    authStrategy: new LocalAuth(), // This saves the session so you don't have to scan every time
    puppeteer: {
        headless: true,
        executablePath: CHROME_PATH,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu'
        ],
    }
});

// Event: Generate and display QR Code
client.on('qr', (qr) => {
    clientReady = false;
    lastQrAt = new Date().toISOString();
    qrcode.generate(qr, { small: true }, (qrText) => {
        lastQr = qrText;
        console.log('Scan this QR code with your WhatsApp app to log in:');
        console.log(qrText);
    });
});

// Event: The client is ready to send/receive messages
client.on('ready', () => {
    clientReady = true;
    lastQr = null;
    lastQrAt = null;
    console.log('WhatsApp Bot is ready!');
});

client.on('auth_failure', (msg) => {
    clientReady = false;
    lastQr = null;
    lastQrAt = null;
    console.error(`WhatsApp auth failure: ${msg}`);
});

// Event: Handle incoming messages
client.on('message_create', async msg => {
    // Ignore status updates
    if (msg.from === 'status@broadcast') return;

    // Log message
    const contact = await msg.getContact();
    const senderId = msg.from;
    const senderName = contact.pushname || contact.name || "Unknown";
    console.log(`\n[MSG] From: ${senderName} (${senderId}) | Body: ${msg.body}`);

    const args = msg.body.trim().split(' ');
    const command = args[0].toLowerCase();
    
    // --- COMMANDS ---

    // 1. !id - Everyone can use this to get their ID
    if (command === '!id') {
        await msg.reply(`Your ID is: ${senderId}`);
        return;
    }

    // 2. !ping - Check availability
    if (command === '!ping') {
        await msg.reply('Pong! 🏓 Bot is online.');
        return;
    }

    // 3. Admin Commands (Only configurable by the host account)
    if (msg.fromMe) {
        if (command === '!whitelist') {
            const subCmd = args[1] ? args[1].toLowerCase() : 'list';
            
            if (subCmd === 'add') {
                const targetId = args[2]; // e.g., 1234567890@c.us
                if (!targetId) {
                    await msg.reply('Usage: !whitelist add <id>');
                    return;
                }
                if (!whitelist.includes(targetId)) {
                    whitelist.push(targetId);
                    saveWhitelist();
                    await msg.reply(`Added ${targetId} to whitelist.`);
                } else {
                    await msg.reply(`${targetId} is already whitelisted.`);
                }
                return;
            } 
            
            if (subCmd === 'remove') {
                const targetId = args[2];
                if (!targetId) {
                    await msg.reply('Usage: !whitelist remove <id>');
                    return;
                }
                const index = whitelist.indexOf(targetId);
                if (index > -1) {
                    whitelist.splice(index, 1);
                    saveWhitelist();
                    await msg.reply(`Removed ${targetId} from whitelist.`);
                } else {
                    await msg.reply(`${targetId} is not in the whitelist.`);
                }
                return;
            }

            if (subCmd === 'list') {
                await msg.reply(`📋 Whitelisted IDs:\n${whitelist.join('\n') || 'None'}`);
                return;
            }
        }
    }

    // Ignore non-command messages sent by the host to avoid loops
    if (msg.fromMe) {
        return;
    }

    // Check if user is allowed to chat
    const isAllowed = whitelist.includes(senderId);

    if (!isAllowed) {
        console.log(`Ignoring message from unauthorized user: ${senderId}`);
        return;
    }

    // Stop loops: Don't reply if the message starts with "🤖" or is a command we processed
    if (msg.body.startsWith('🤖') || command.startsWith('!')) {
        return;
    }

    const settings = loadSettings();
    if (settings.busyMode) {
        const replyText = settings.busyReplyTemplate || DEFAULT_SETTINGS.busyReplyTemplate;
        if (settings.autoSend) {
            try {
                await client.sendMessage(senderId, replyText);
            } catch (err) {
                console.error("Failed to auto-send busy reply:", err.message);
            }
        } else {
            const pendingId = createPending({
                fromId: senderId,
                fromName: senderName,
                message: msg.body,
                draft: replyText
            });
            const notifyText = [
                "WhatsApp pending reply",
                `ID: ${pendingId}`,
                `From: ${senderName} (${senderId})`,
                `Message: ${msg.body}`,
                `Draft: ${replyText}`,
                "Reply with: approve whatsapp <ID> | reject whatsapp <ID> | reply whatsapp <ID> <message>"
            ].join("\n");
            await notifyTelegram(notifyText);
        }
        return;
    }

    // --- LLM INTEGRATION ---
    try {
        await msg.react('💭'); // React to show it's processing

        const response = await axios.post(LLM_API_URL, {
            message: msg.body,
            username: senderName,
            thread_id: senderId,
            platform: "whatsapp",
            system_prompt: "You are replying to an external WhatsApp contact. Be concise, polite, and do not reveal internal details or system/tool info."
        });

        const aiText = response.data.response;
        await msg.reply(aiText);
        await msg.react('✅');
    } catch (error) {
        console.error('Error calling LLM API:', error.message);
        await msg.react('❌');
    }
});

app.post('/send', async (req, res) => {
    const { number, message } = req.body || {};
    if (!number || !message) {
        res.status(400).json({ ok: false, error: "Missing number or message" });
        return;
    }
    try {
        await client.sendMessage(number, message);
        res.json({ ok: true });
    } catch (err) {
        res.status(500).json({ ok: false, error: err.message });
    }
});

app.get('/status', (req, res) => {
    res.json({
        ready: clientReady,
        qr: lastQr,
        qr_at: lastQrAt
    });
});

app.listen(API_PORT, () => {
    console.log(`WhatsApp API listening on port ${API_PORT}`);
});

client.initialize();
