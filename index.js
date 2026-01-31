const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const fs = require('fs');
const path = require('path');

// --- Configuration ---
const WHITELIST_FILE = path.join(__dirname, 'whitelist.json');
const LLM_API_URL = 'http://localhost:8000/chat';

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

// Initialize the WhatsApp client
const client = new Client({
    authStrategy: new LocalAuth(), // This saves the session so you don't have to scan every time
    puppeteer: {
        args: ['--no-sandbox'],
    }
});

// Event: Generate and display QR Code
client.on('qr', (qr) => {
    console.log('Scan this QR code with your WhatsApp app to log in:');
    qrcode.generate(qr, { small: true });
});

// Event: The client is ready to send/receive messages
client.on('ready', () => {
    console.log('WhatsApp Bot is ready!');
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

    // --- LLM INTEGRATION ---
    
    // Check if user is allowed to chat with LLM
    // Allowed if: It's me (the host) OR the sender is in the whitelist
    const isAllowed = msg.fromMe || whitelist.includes(senderId);

    if (!isAllowed) {
        // Optionally reply that they are not authorized, or just ignore
        console.log(`Ignoring message from unauthorized user: ${senderId}`);
        return;
    }

    // Stop loops: Don't reply if the message starts with "🤖" or is a command we processed
    if (msg.body.startsWith('🤖') || command.startsWith('!')) {
        return;
    }

    try {
        // Prepare context for LLM
        // We use the senderIdas 'username' or 'thread_id' to keep conversations separate
        await msg.react('💭'); // React to show it's processing

        const response = await axios.post(LLM_API_URL, {
            message: msg.body,
            username: senderName,
            thread_id: senderId, // Keep history per user
            platform: "whatsapp"
        });

        const aiText = response.data.response;
        await msg.reply(aiText);
        await msg.react('✅'); // React to show success

    } catch (error) {
        console.error('Error calling LLM API:', error.message);
        await msg.react('❌');
        
        // Only show detailed error to Admin
        if (msg.fromMe) {
             await msg.reply(`❌ LLM Error: ${error.message}\nMake sure 'python llm/api.py' is running.`);
        }
    }
});
/* Lines 42-90 omitted for brevity (old code replacement) */
