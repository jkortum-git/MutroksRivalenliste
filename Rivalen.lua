local frame = CreateFrame("Frame")
local seen = {}
local openEditor, refreshEditor
local debugEnabled = false
local function say(msg)
    print("|cffff9944Rivalenliste:|r " .. msg)
end
local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end
local function identity(full)
    full = full:match("^%s*(.-)%s*$"):gsub("%s+", " ")
    local first, last = full:match("^([^%s%-]+)[ %-]([^%s%-]+)$")
    if not first or full:find("[%d%p%c]") and not full:match("^[%a\128-\255]+%-[%a\128-\255]+$") then return end
    local display = first .. " " .. last
    -- Keep the historical lookup key so existing entries and notes still match.
    return (strlower or string.lower)(first .. "-" .. last), display
end
local function unitIdentity(unit)
    if not unit then return end
    local player = UnitIsPlayer(unit)
    if not readable(player) or not player then return end
    local first, last = (UnitNameUnmodified or UnitName)(unit)
    if not readable(first) or not readable(last) or not first or first == UNKNOWNOBJECT then return end
    if last and last ~= "" and not identity(first) then first = first .. " " .. last end
    return identity(first)
end
local function inspect(unit)
    if not MutroksRivalenDB or IsInInstance() then return end
    local key, display = unitIdentity(unit)
    local rival = key and MutroksRivalenDB[key]
    if not rival then return end
    if not rival.verified then
        rival.verified, rival.name = true, display
        if refreshEditor then refreshEditor() end
    end
    local now = GetTime()
    local previous = seen[key]
    seen[key] = now
    if previous and now - previous < 60 then return end
    local msg = "Rivale gesichtet: " .. rival.name
    if rival.note ~= "" then msg = msg .. " – " .. rival.note end
    say(msg)
    UIErrorsFrame:AddMessage(msg, 1, 0.4, 0.1)
    PlaySound(8959, "Master")
    if debugEnabled then say("Erkennung über " .. unit) end
end
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("NAME_PLATE_UNIT_ADDED")
frame:RegisterEvent("UPDATE_MOUSEOVER_UNIT")
frame:RegisterEvent("PLAYER_TARGET_CHANGED")
frame:SetScript("OnEvent", function(_, event, arg)
    if event == "ADDON_LOADED" then
        if arg == "MutroksRivalenliste" then MutroksRivalenDB = MutroksRivalenDB or {} end
    elseif event == "PLAYER_ENTERING_WORLD" then
        wipe(seen)
        inspect("target")
    elseif event == "NAME_PLATE_UNIT_ADDED" then inspect(arg)
    elseif event == "UPDATE_MOUSEOVER_UNIT" then inspect("mouseover")
    else inspect("target") end
end)
SLASH_MUTROKSRIVALEN1 = "/rivalen"
SlashCmdList.MUTROKSRIVALEN = function(input)
    local action, rest = input:match("^%s*(%S*)%s*(.-)%s*$")
    if action == "menü" or action == "menue" then openEditor(); return end
    if action == "+" or action == "-" then
        local name, note = rest:match("^(%S*)%s*(.*)$")
        if name ~= "" and name ~= "ziel" and not name:find("-", 1, true) then
            local surname, remainder = note:match("^(%S+)%s*(.*)$")
            if surname then name, note = name .. " " .. surname, remainder end
        end
        local key, display
        if name == "" or name == "ziel" then key, display = unitIdentity("target")
        else key, display = identity(name) end
        if not key then say("Spieler anvisieren oder Vorname Nachname angeben."); return end
        if action == "+" then
            MutroksRivalenDB[key] = {name = display, note = note:gsub("|", ""), verified = (key == unitIdentity("target")) or (MutroksRivalenDB[key] and MutroksRivalenDB[key].verified)}
            say(display .. " eingetragen.")
        elseif MutroksRivalenDB[key] then
            MutroksRivalenDB[key], seen[key] = nil, nil
            say(display .. " entfernt.")
        else say(display .. " steht nicht auf der Liste.") end
        if refreshEditor then refreshEditor() end
    elseif action == "diagnose" then
        debugEnabled = not debugEnabled
        say(debugEnabled and "Sitzungsdiagnose an." or "Sitzungsdiagnose aus.")
    else
        local rows = {}
        for _, r in pairs(MutroksRivalenDB) do
            rows[#rows+1] = r.name .. (r.note ~= "" and (" – " .. r.note) or "")
        end
        table.sort(rows)
        say(#rows .. " Einträge.")
        for _, row in ipairs(rows) do print(row) end
        say("/rivalen + ziel [Notiz] oder /rivalen + Vorname Nachname [Notiz]; entfernen mit /rivalen - ziel oder /rivalen - Vorname Nachname.")
    end
end


local window = CreateFrame("Frame", "MutroksRivalenEditor", UIParent, "BasicFrameTemplateWithInset")
window:SetSize(430, 430)
window:SetPoint("CENTER")
window:SetFrameStrata("DIALOG")
window:EnableMouse(true)
window:Hide()
table.insert(UISpecialFrames, "MutroksRivalenEditor")

local function label(text, x, y)
    local font = window:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    font:SetPoint("TOPLEFT", x, y)
    font:SetText(text)
    return font
end
label("Mutroks Rivalenliste", 12, -5)
local heading = label("Rivalen", 18, -39)
local function button(text, x, y, width, click)
    local b = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
    b:SetPoint("TOPLEFT", x, y)
    b:SetSize(width, 24)
    b:SetText(text)
    b:SetScript("OnClick", click)
    return b
end
local function input(title, y)
    label(title, 18, y)
    local box = CreateFrame("EditBox", nil, window, "InputBoxTemplate")
    box:SetPoint("TOPLEFT", 23, y - 17)
    box:SetSize(383, 24)
    box:SetAutoFocus(false)
    box:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    return box
end
local name = input("Vorname Nachname", -253)
local note = input("Notiz", -302)
local feedback = label("", 18, -397)
local page, selected = 1, nil
local rows, keys = {}, {}
local previous, following, remove
local function selectEntry(key)
    selected = key
    local entry = key and MutroksRivalenDB[key]
    name:SetText(entry and entry.name or "")
    note:SetText(entry and entry.note or "")
    remove:SetEnabled(entry ~= nil)
    feedback:SetText("")
end
refreshEditor = function()
    if not window:IsShown() then return end
    keys = {}
    for key in pairs(MutroksRivalenDB) do keys[#keys + 1] = key end
    table.sort(keys)
    local pages = math.max(1, math.ceil(#keys / #rows))
    page = math.min(page, pages)
    heading:SetText(("Rivalen (%d)  ·  Seite %d/%d"):format(#keys, page, pages))
    previous:SetEnabled(page > 1)
    following:SetEnabled(page < pages)
    if selected and not MutroksRivalenDB[selected] then selectEntry(nil) end
    for i, row in ipairs(rows) do
        row.key = keys[(page - 1) * #rows + i]
        row:SetShown(row.key ~= nil)
        if row.key then
            local entry = MutroksRivalenDB[row.key]
            row:SetText(entry.name .. (entry.verified and "  (Spieler bestätigt)" or "  (Unbestätigt)"))
        end
    end
end
previous = button("<", 335, -31, 32, function() page = page - 1; refreshEditor() end)
following = button(">", 373, -31, 32, function() page = page + 1; refreshEditor() end)
for i = 1, 6 do
    rows[i] = button("", 18, -60 - (i-1)*25, 389, function(self) selectEntry(self.key) end)
end
button("Neuer Eintrag", 18, -217, 144, function()
    selectEntry(nil)
    name:SetFocus()
end)
button("Ziel übernehmen", 170, -217, 145, function()
    local key, display = unitIdentity("target")
    if not key then feedback:SetText("Bitte einen Spieler anvisieren."); return end
    selectEntry(MutroksRivalenDB[key] and key or nil)
    name:SetText(display)
end)
local function save()
    local raw = name:GetText():match("^%s*(.-)%s*$")
    local key, display = identity(raw)
    if not key then
        feedback:SetText("Bitte Vorname und Nachname eingeben.")
        return
    end
    if key ~= selected and MutroksRivalenDB[key] then
        feedback:SetText("Bereits vorhanden. Zum Bearbeiten den Eintrag anklicken.")
        return
    end
    local verified = key == unitIdentity("target") or (MutroksRivalenDB[key] and MutroksRivalenDB[key].verified)
    if selected and selected ~= key then MutroksRivalenDB[selected], seen[selected] = nil, nil end
    MutroksRivalenDB[key] = {name = display, note = note:GetText():gsub("|", ""), verified = verified}
    selectEntry(key)
    name:ClearFocus()
    note:ClearFocus()
    refreshEditor()
    for i, listed in ipairs(keys) do
        if listed == key then page = math.ceil(i / #rows); break end
    end
    refreshEditor()
    feedback:SetText("Eintrag gespeichert.")
end
button("Speichern", 18, -358, 145, save)
remove = button("Entfernen", 170, -358, 145, function()
    if not selected then return end
    MutroksRivalenDB[selected], seen[selected] = nil, nil
    selectEntry(nil)
    refreshEditor()
    feedback:SetText("Eintrag entfernt.")
end)
window:SetScript("OnShow", function() selectEntry(nil); refreshEditor() end)
openEditor = function() window:SetShown(not window:IsShown()) end
local launcher = CreateFrame("Button", "MutroksRivalenlisteMinimapButton", Minimap)
launcher:SetSize(31, 31)
launcher:SetPoint("BOTTOMLEFT", Minimap, "BOTTOMLEFT", 5, 8)
launcher:SetFrameLevel(Minimap:GetFrameLevel() + 8)
launcher.icon = launcher:CreateTexture(nil, "ARTWORK")
launcher.icon:SetSize(20, 20)
launcher.icon:SetPoint("CENTER", -1, 1)
launcher.icon:SetTexture("Interface\\Icons\\Ability_Hunter_SniperShot")
local border = launcher:CreateTexture(nil, "OVERLAY")
border:SetSize(53, 53)
border:SetPoint("TOPLEFT")
border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
launcher:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
launcher:SetScript("OnClick", openEditor)
launcher:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:AddLine("Mutroks Rivalenliste")
    GameTooltip:AddLine("Klicken, um die Liste zu bearbeiten.", 1, 1, 1)
    GameTooltip:Show()
end)
launcher:SetScript("OnLeave", function() GameTooltip:Hide() end)
