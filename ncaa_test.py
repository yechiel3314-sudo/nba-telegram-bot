const axios = require("axios");
const TelegramBot = require("node-telegram-bot-api");
const moment = require("moment-timezone");

const TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE";
const CHAT_ID = "-1003808107418"; // ה-Chat ID הנכון מהתמונות שלך

const bot = new TelegramBot(TOKEN, { polling: false });
const trackedGames = {};

function nowTime() {
    return moment().tz("Asia/Jerusalem").format("HH:mm:ss");
}

async function fetchGames() {
    try {
        const res = await axios.get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
            { timeout: 10000 }
        );
        return res.data.events || [];
    } catch (e) {
        console.log("Scoreboard error:", e.message);
        return [];
    }
}

async function fetchBoxScore(gameId) {
    try {
        const res = await axios.get(
            `https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event=${gameId}`,
            { timeout: 10000 }
        );
        return res.data;
    } catch (e) {
        console.log(`Boxscore error for ${gameId}:`, e.message);
        return null;
    }
}

function getTopPlayers(teamData) {
    if (!teamData || !teamData.players || !teamData.players[0]) return null;
    
    const athletes = teamData.players[0].statistics[0].athletes;
    
    // מיון לפי נקודות (במכללות אינדקס 12 הוא לרוב הנקודות)
    const sorted = [...athletes].sort((a, b) => {
        const ptsA = parseInt(a.stats[12]) || 0;
        const ptsB = parseInt(b.stats[12]) || 0;
        return ptsB - ptsA;
    });

    return {
        leader: sorted[0],
        second: sorted[1],
        bench: sorted.find(p => p.starter === false) || sorted[2]
    };
}

function formatPlayer(p) {
    if (!p || !p.athlete) return "אין נתונים";
    const s = p.stats;
    // אינדקסים למכללות: 12=נק', 6=ריב', 7=אס'
    return `*${p.athlete.displayName}*: ${s[12]} נק', ${s[6]} ריב', ${s[7]} אס'`;
}

async function handleGames() {
    console.log(`[${nowTime()}] מריץ סריקה...`);
    const games = await fetchGames();

    for (const game of games) {
        const gameId = game.id;
        const competition = game.competitions[0];
        const status = game.status.type.name;
        
        const homeTeam = competition.competitors.find(c => c.homeAway === 'home');
        const awayTeam = competition.competitors.find(c => c.homeAway === 'away');
        
        const homeScore = parseInt(homeTeam.score) || 0;
        const awayScore = parseInt(awayTeam.score) || 0;

        if (!trackedGames[gameId]) {
            trackedGames[gameId] = { started: false, lastPeriod: 0, finalSent: false };
        }

        // זיהוי משחק פעיל (גם אם הסטטוס ב-API תקוע על Scheduled)
        const isActuallyPlaying = status === "STATUS_IN_PROGRESS" || (homeScore > 0 || awayScore > 0);

        if (isActuallyPlaying && status !== "STATUS_FINAL") {
            if (!trackedGames[gameId].started) {
                trackedGames[gameId].started = true;
                bot.sendMessage(CHAT_ID, `🔥 *המשחק יצא לדרך!* 🔥\n🏀 ${game.name}\n🕒 ${nowTime()}`, { parse_mode: "Markdown" });
            }

            const currentPeriod = game.status.period;
            if (currentPeriod !== trackedGames[gameId].lastPeriod) {
                const box = await fetchBoxScore(gameId);
                if (box && box.boxscore && box.boxscore.players) {
                    const homeBox = box.boxscore.players.find(t => t.team.id === homeTeam.id);
                    const awayBox = box.boxscore.players.find(t => t.team.id === awayTeam.id);

                    const homeTop = getTopPlayers(homeBox);
                    const awayTop = getTopPlayers(awayBox);

                    let msg = `🏀 *עדכון מחצית/רבע ${currentPeriod}:* ${game.name}\n`;
                    msg += `תוצאה: ${awayTeam.team.shortDisplayName} ${awayScore} - ${homeScore} ${homeTeam.team.shortDisplayName}\n\n`;
                    
                    if (homeTop && awayTop) {
                        msg += `🔥 *${homeTeam.team.shortDisplayName}:*\n• ${formatPlayer(homeTop.leader)}\n• ${formatPlayer(homeTop.bench)} (ספסל)\n\n`;
                        msg += `🔥 *${awayTeam.team.shortDisplayName}:*\n• ${formatPlayer(awayTop.leader)}\n• ${formatPlayer(awayTop.bench)} (ספסל)`;
                    }

                    bot.sendMessage(CHAT_ID, msg, { parse_mode: "Markdown" });
                    trackedGames[gameId].lastPeriod = currentPeriod;
                }
            }
        }

        if (status === "STATUS_FINAL" && !trackedGames[gameId].finalSent) {
            trackedGames[gameId].finalSent = true;
            bot.sendMessage(CHAT_ID, `🏁 *סיום המשחק!* 🏁\n🏀 ${game.name}\nתוצאה סופית: ${awayScore} - ${homeScore}`, { parse_mode: "Markdown" });
        }
    }
}

setInterval(handleGames, 45000); // סריקה כל 45 שניות
handleGames();
