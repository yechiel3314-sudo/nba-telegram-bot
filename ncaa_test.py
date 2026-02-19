const axios = require("axios");
const TelegramBot = require("node-telegram-bot-api");
const moment = require("moment-timezone");

TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
const CHAT_ID = "PUT_YOUR_CHAT_ID_HERE";

const bot = new TelegramBot(TOKEN);
const trackedGames = {};

function nowTime() {
  return moment().tz("Asia/Jerusalem").format("HH:mm:ss");
}

async function fetchGames() {
  try {
    const res = await axios.get(
      "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
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
      `https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event=${gameId}`
    );
    return res.data;
  } catch (e) {
    console.log("Boxscore error:", e.message);
    return null;
  }
}

function topPlayers(team) {
  const players = team.statistics[0].athletes;

  const sorted = players.sort((a, b) =>
    parseInt(b.stats[13]) - parseInt(a.stats[13])
  );

  return {
    leader: sorted[0],
    second: sorted[1],
    bench: sorted.find(p => p.starter === false)
  };
}

function formatPlayer(p) {
  if (!p) return "לא זמין";
  return `${p.athlete.displayName}: ${p.stats[13]} נק', ${p.stats[6]} ריב', ${p.stats[7]} אס' (${p.stats[9] || 0} חט', ${p.stats[10] || 0} חס')`;
}

async function handleGames() {
  const games = await fetchGames();

  for (const game of games) {
    const gameId = game.id;
    const status = game.status.type.name;

    if (!trackedGames[gameId]) {
      trackedGames[gameId] = { started: false, lastPeriod: 0 };
    }

    if (status === "STATUS_IN_PROGRESS") {
      if (!trackedGames[gameId].started) {
        trackedGames[gameId].started = true;
        bot.sendMessage(
          CHAT_ID,
          `🔥 המשחק יצא לדרך! 🔥\n🕒 ${nowTime()}\n🏀 ${game.name}`
        );
      }

      const box = await fetchBoxScore(gameId);
      if (!box) continue;

      const home = box.boxscore.teams[0];
      const away = box.boxscore.teams[1];

      const homeTop = topPlayers(home);
      const awayTop = topPlayers(away);

      const currentPeriod = box.header.competitions[0].status.period;

      if (currentPeriod !== trackedGames[gameId].lastPeriod) {
        trackedGames[gameId].lastPeriod = currentPeriod;

        bot.sendMessage(
          CHAT_ID,
`🏀 סוף רבע ${currentPeriod}: ${away.team.displayName} 🆚 ${home.team.displayName} 🏀
🕒 ${nowTime()}

🔹 ${home.team.displayName} ${home.score}-${away.score}

🔥 ${home.team.displayName}:
• 🔝 קלע מוביל: ${formatPlayer(homeTop.leader)}
• 🏀 סקורר שני: ${formatPlayer(homeTop.second)}
• ⚡ מהספסל: ${formatPlayer(homeTop.bench)}

🔥 ${away.team.displayName}:
• 🔝 קלע מוביל: ${formatPlayer(awayTop.leader)}
• 🏀 סקורר שני: ${formatPlayer(awayTop.second)}
• ⚡ מהספסל: ${formatPlayer(awayTop.bench)}
`
        );
      }
    }

    if (status === "STATUS_FINAL") {
      if (!trackedGames[gameId].finalSent) {
        trackedGames[gameId].finalSent = true;

        const box = await fetchBoxScore(gameId);
        if (!box) continue;

        const home = box.boxscore.teams[0];
        const away = box.boxscore.teams[1];

        bot.sendMessage(
          CHAT_ID,
`🏁 סיום המשחק! 🏁
🕒 ${nowTime()}
🏀 ${game.name}
תוצאה סופית: ${home.score}-${away.score}`
        );
      }
    }
  }
}

setInterval(handleGames, 20000);
