$(document).ready(function() {
    console.log("Document is ready. Loading data...");
    $.when(
        $.getJSON('https://raw.githubusercontent.com/Volley-Batch/Volley-Batch.github.io/main/teams.json'),
        $.getJSON('https://raw.githubusercontent.com/Volley-Batch/Volley-Batch.github.io/main/stats.json')
    ).done(function(teamsData, statsData) {
        // teamsData[0] and statsData[0] contain the actual JSON objects
        const teams = teamsData[0];
        const stats = statsData[0];
        
        // update last update time
        last_update = stats.last_update; // e.g., "2025-10-29T20:22:00"
        last_update = new Date(last_update);    // convert to Date object
        // format options
        let options = { 
            day: 'numeric', 
            month: 'long', 
            year: 'numeric', 
            hour: '2-digit', 
            minute: '2-digit',
            hour12: false // 24-hour format
        };
        last_update = last_update.toLocaleString('en-GB', options);
        $('#stats-last-update').text(`Last update: ${last_update}`);

        const $tbody = $('#ranking-table-body');
        $tbody.empty(); // clear existing rows if needed

        // Map country codes to flag emojis
        function countryCodeToFlag(code) {
            if (!code || code.length !== 2) return '';

            const base = 0x1F1E6; // Unicode for 🇦
            const chars = code.toUpperCase().split('');

            return String.fromCodePoint(
                base + chars[0].charCodeAt(0) - 65,
                base + chars[1].charCodeAt(0) - 65
            );
        }

        // Sort teams by ELO rating in descending order
        teams.sort((a, b) => b.elo - a.elo);

        teams.forEach((team, index) => {
            const flag = countryCodeToFlag(team.country_iso2);
            const row = `
            <tr>
                <th scope="row" data-label="#">${index + 1}</th>
                <td data-label="Team">${flag} ${team.name}</td>
                <td data-label="Rating">${parseFloat(team.elo).toFixed(1)}</td>
            </tr>
            `;

            $tbody.append(row);
        });
    }).fail(function() {
        console.error("Failed to load JSON files.");
    });
});
