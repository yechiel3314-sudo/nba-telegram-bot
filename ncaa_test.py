const axios = require("axios");
const TelegramBot = require("node-telegram-bot-api");
const moment = require("moment-timezone");

const TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE";
const CHAT_ID = "-1003808107418";

const bot = new TelegramBot(TOKEN, { polling: false });
const trackedGames = {};

function nowTime() {
    return moment().tz("Asia/Jerusalem").format("HH:mm:ss");
}

async function handleGames() {
    console.log(`[${nowTime()}] סריקה רצה...`);
    try {
        const res = await axios.get("https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard", { timeout: 10000 });
        const games = res.data.events || [];

        for (const game of games) {
            const gameId = game.id;
            const status = game.status.type.name;
            const competition = game.competitions[0];
            const home = competition.competitors.find(c => c.homeAway === 'home');
            const away = competition.competitors.find(c => c.homeAway === 'away');
            
            const homeScore = home.score;
            const awayScore = away.score;

            // אתחול מעקב למשחק חדש
            if (!trackedGames[gameId]) {
                trackedGames[gameId] = { 
                    started: false, 
                    lastPeriod: 0, 
                    lastUpdate: 0, // זמן העדכון האחרון במילישניות
                    finalSent: false 
                };
            }

            if (status === "STATUS_IN_PROGRESS") {
                
                // הודעת פתיחת משחק
                if (!trackedGames[gameId].started) {
                    trackedGames[gameId].started = true;
                    bot.sendMessage(CHAT_ID, `🔥 *המשחק התחיל!* 🔥\n🏀 ${game.name}\n🕒 ${nowTime()}`, { parse_mode: "Markdown" });
                }

                const currentTime = Date.now();
                // חישוב כמה דקות עברו מאז העדכון האחרון
                const minutesSinceUpdate = (currentTime - trackedGames[gameId].lastUpdate) / 60000;
                const currentPeriod = game.status.period;

                // שליחת עדכון אם עברו 10 דקות (או יותר) או אם השתנתה המחצית
                if (minutesSinceUpdate >= 10 || currentPeriod !== trackedGames[gameId].lastPeriod) {
                    
                    try {
                        const summary = await axios.get(`https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event=${gameId}`);
                        const teamsData = summary.data.boxscore.teams;
                        
                        if (teamsData) {
                            let msg = `📢 *עדכון משחק (כל 10 דקות):* \n🏀 ${game.name}\n⏱️ שעון: ${game.status.displayClock} (חצי ${currentPeriod})\n`;
                            msg += `📊 תוצאה: ${away.team.shortDisplayName} ${awayScore} - ${homeScore} ${home.team.shortDisplayName}\n\n`;

                            const getTopPlayer = (teamData) => {
                                const athletes = teamData.statistics[0].athletes;
                                // מיון לפי נקודות (אינדקס 13 כפי שעבד לך בעבר)
                                const sorted = [...athletes].sort((a,b) => (parseInt(b.stats[13]) || 0) - (parseInt(a.stats[13]) || 0));
                                const p = sorted[0];
                                return p ? `⭐ *${p.athlete.displayName}*: ${p.stats[13]} נק', ${p.stats[6]} ריב'` : "אין נתונים";
                            };

                            msg += `🏠 *${home.team.shortDisplayName}:* ${getTopPlayer(teamsData[0])}\n`;
                            msg += `🚀 *${away.team.shortDisplayName}:* ${getTopPlayer(teamsData[1])}`;

                            bot.sendMessage(CHAT_ID, msg, { parse_mode: "Markdown" });
                            
                            // עדכון זמן השליחה האחרון והמחצית האחרונה
                            trackedGames[gameId].lastUpdate = currentTime;
                            trackedGames[gameId].lastPeriod = currentPeriod;
                        }
                    } catch (e) {
                        console.log("Error fetching detailed stats:", e.message);
                    }
                }
            }

            // הודעת סיום משחק
            if (status === "STATUS_FINAL" && !trackedGames[gameId].finalSent) {
                trackedGames[gameId].finalSent = true;
                bot.sendMessage(CHAT_ID, `🏁 *סיום משחק:* ${game.name}\nתוצאה סופית: ${awayScore} - ${homeScore}`, { parse_mode: "Markdown" });
            }
        }
    } catch (error) {
        console.log("General scan error:", error.message);
    }
}

// הרצה כל 45 שניות
setInterval(handleGames, 45000);
handleGames();
