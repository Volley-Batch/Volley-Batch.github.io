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

        teams.forEach((team, index) => {            
            const change = '+10';
            const rating = '1000';
            const plusMinus = '+2.0';

            const row = `
            <tr>
                <th scope="row" data-label="#">${index + 1}</th>
                <td data-label="Change">${change}</td>
                <td data-label="Team">${team.name}</td>
                <td data-label="Country">Italy</td>
                <td data-label="Rating">${team.elo}</td>
                <td data-label="+/-">${plusMinus}</td>
            </tr>
            `;

            $tbody.append(row);
        });
    }).fail(function() {
        console.error("Failed to load JSON files.");
    });
});
