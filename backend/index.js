const express = require('express');
const app = express()
const port = 3002
const path = require('path');

const Pusher = require("pusher");
const pusher = new Pusher({
    appId: process.env.PUSHER_APPID,
    key: process.env.PUSHER_KEY,
    secret: process.env.PUSHER_SECRET,
    cluster: process.env.PUSHER_CLUSTER,
    useTLS: true
  });

/*
LABELS:
- Wachten
- Gepland
- Onderweg
- Bevestigen
*/

var bestellingen = []

function initValues() {
  bestellingen = []
  return {
    label: "Wachten",
    route: [],
    vertrektijd: 0,
    afstanden: {
      // 0.05 m/s rechtdoor, 34 sec bocht
      tussenstuk: 20, // seconden per kamer of start->kamer
      bocht: 60, // seconden in bocht
      kamer: 30, // seconden in kamer
    },
    kamers: {
      1: {
        buttonText: 'Bestellen',
        buttonColor: "",
      },
      2: {
        buttonText: 'Bestellen',
        buttonColor: "",
      },
      3: {
        buttonText: 'Bestellen',
        buttonColor: "",
      },
    },
    banner: {
      statusIcon: "mdi-sleep",
      statusLabel: "Het KoffieKarretje wacht op een bestelling",
      statusType: "success",
    }
  }
}

var status = initValues()

function updateStatus() {
  pusher.trigger("status", "update", {
    status, bestellingen
  });
}

// App
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, '/index.html'))
})

app.get('/admin', (req, res) => {
  res.sendFile(path.join(__dirname, '/admin.html'))
})

// App
app.get('/bestel/:kamer', (req, res) => {
  if (bestellingen.includes(Number(req.params.kamer))) {
    res.send("NOK")
    return
  }
  if (status.kamers[req.params.kamer].buttonText != "Bestellen") {
    res.send("NOK")
    return
  }
  if (status.label == "Wachten") {
    status.label = "Gepland"
    status.vertrektijd = new Date().getTime() + 1000 * 10 // 60 in werkelijke omgeving

    status.banner.statusIcon = "mdi-clock"
    status.banner.statusLabel = "Het KoffieKarretje vertrekt binnen enkele seconden";
    status.banner.statusType = "info"
  }
  bestellingen.push(Number(req.params.kamer))
  status.kamers[req.params.kamer].buttonText = "Besteld"
  status.kamers[req.params.kamer].buttonColor = "success"
  updateStatus()
  res.send("OK")
})

// Agent
app.get('/moetikvertrekken', (req, res) => {
  if (status.label != "Gepland") {
    return res.send("NEE")
  }
  if (status.vertrektijd == 0) {
    return res.send("NEE")
  }
  if (new Date().getTime() > status.vertrektijd) {
    return res.send("JA")
  }
  return res.send("NEE")
})

// Agent
app.get('/vertrek', (req, res) => {
  if (bestellingen.length == 0) {
    return res.send("0")
  }
  status.label = "Onderweg"
  status.vertrektijd = 0
  status.route = bestellingen
  bestellingen = []

  for (let kamer in status.kamers) {
    if (status.route.includes(Number(kamer))) {
      status.kamers[kamer].buttonText = "Onderweg"
      status.kamers[kamer].buttonColor = "warning"
    } else {
      status.kamers[kamer].buttonText = "Bestellen"
      status.kamers[kamer].buttonColor = ""
    }
  }

  status.banner.statusIcon = "mdi-coffee-to-go"
  status.banner.statusLabel = "Het KoffieKarretje is onderweg";
  status.banner.statusType = "warning"

  status.route.sort()
  res.send(String(status.route.shift()))
  updateStatus()
})

app.get('/reset', (req, res) => {
  status = initValues()
  updateStatus()
  res.send("OK")
})

// Agent
app.get('/volgende', (req, res) => {
  if (status.route.length == 0) {
    updateStatus()
    return res.send("0")
  }
  var kamer = status.route.shift()
  res.send(String(kamer))
  updateStatus()
})

// Agent
app.get('/gearriveerd/:kamer', (req, res) => {
  status.label = "Bevestigen"
  pusher.trigger("status", "aangekomen", req.params.kamer);
  updateStatus()
  res.send("OK")
})

app.get('/alert/:kamer', (req, res) => {
  status.label = "Onderweg"
  status.kamers[req.params.kamer].buttonText = "Niet aangekomen"
  status.kamers[req.params.kamer].buttonColor = "error"
  pusher.trigger("status", "alert", req.params.kamer);
  updateStatus()
  res.send("OK")
})

// App
app.get('/bevestig/:kamer', (req, res) => {
  status.label = "Onderweg"

  status.kamers[req.params.kamer].buttonText = "Bestellen"
  status.kamers[req.params.kamer].buttonColor = ""
  updateStatus()
  res.send("OK")
})

// Agent
app.get('/einde', (req, res) => {
  if (bestellingen.length > 0) {
    status.label = "Gepland"
    status.vertrektijd = new Date().getTime()
    status.banner.statusIcon = "mdi-clock"
    status.banner.statusLabel = "Het KoffieKarretje komt binnen enkele seconden terug";
    status.banner.statusType = "info"
  } else {
    status.label = "Wachten"
    status.vertrektijd = 0
    status.banner.statusIcon = "mdi-sleep"
    status.banner.statusLabel = "Het KoffieKarretje wacht op een bestelling";
    status.banner.statusType = "success"
  }
  status.route = []

  for (let kamer in status.kamers) {
    if (status.kamers[kamer].buttonText == "Onderweg") {
      status.kamers[kamer].buttonText = "Bestellen"
      status.kamers[kamer].buttonColor = ""
    }
  }
  updateStatus()
  return res.send("OK")
})

// App + Agent
app.get('/status', (req, res) => {
  res.send({
    status, bestellingen
  })
})

app.listen(port, () => {
  console.log(`Example app listening on port ${port}`)
})