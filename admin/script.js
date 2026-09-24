async function loadRevenue() {

    const API = "https://queueless-api-production.com";


    const data =
        await response.json();


    document.getElementById(
        "tokens"
    ).innerText =
        data.total_tokens;


    document.getElementById(
        "revenue"
    ).innerText =
        "₹" + data.total_revenue;
}


loadRevenue();


setInterval(
    loadRevenue,
    5000
);