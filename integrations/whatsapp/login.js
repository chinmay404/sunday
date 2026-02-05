const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const path = require('path');

const CHROME_PATH = process.env.CHROME_PATH || process.env.PUPPETEER_EXECUTABLE_PATH || "/usr/bin/chromium";
const AUTH_PATH = path.join(__dirname, '.wwebjs_auth');

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: AUTH_PATH }),
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

client.on('qr', (qr) => {
    console.log('Scan this QR code with WhatsApp (Linked Devices):');
    qrcode.generate(qr, { small: true });
});

client.on('ready', async () => {
    console.log('WhatsApp login successful. You can start the API server now.');
    try {
        await client.destroy();
    } finally {
        process.exit(0);
    }
});

client.on('auth_failure', (msg) => {
    console.error(`WhatsApp auth failure: ${msg}`);
    process.exit(1);
});

client.initialize();
