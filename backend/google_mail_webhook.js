/**
 * CarePath - 100% Free Production Email Webhook via Google Apps Script
 * ====================================================================
 * This script sends emails to ANY email address in the world (any hospital, doctor, patient)
 * directly from your Gmail account (mangarajesh58@gmail.com).
 * 
 * - 0 Domain Verification Needed
 * - 0 Port Blocks (runs over standard HTTPS 443)
 * - 100% Inbox Delivery (not Spam)
 * - 100 Free Emails / Day
 * 
 * HOW TO DEPLOY IN 60 SECONDS:
 * 1. Open https://script.google.com while logged into your Google account (mangarajesh58@gmail.com).
 * 2. Click "New project" (name it "CarePath Email Dispatcher").
 * 3. Replace all existing text with this exact code below.
 * 4. Click "Deploy" (blue button at top right) -> "New deployment".
 * 5. Click the gear icon next to "Select type" -> select "Web app".
 * 6. Set Description: "CarePath Email Dispatcher"
 * 7. Set "Execute as": "Me (mangarajesh58@gmail.com)"
 * 8. Set "Who has access": "Anyone"  <-- IMPORTANT!
 * 9. Click "Deploy" -> "Authorize access" -> choose your account -> Advanced -> "Go to CarePath Email Dispatcher (unsafe)" -> Allow.
 * 10. Copy the Web app URL (looks like: https://script.google.com/macros/s/AKfycb.../exec).
 * 11. Add it to Render Environment Variables as:
 *     Key: GMAIL_WEBHOOK_URL
 *     Value: [Your Web app URL]
 */

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var to = data.to;
    var subject = data.subject || "CarePath Notification";
    var body = data.body || "";
    var html = data.html || "";

    if (!to) {
      return ContentService.createTextOutput(JSON.stringify({
        status: "error",
        message: "Missing 'to' recipient address"
      })).setMimeType(ContentService.MimeType.JSON);
    }

    // Send email using GmailApp
    GmailApp.sendEmail(to, subject, body, {
      htmlBody: html,
      name: "CarePath Healthcare"
    });

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      message: "Email dispatched successfully to " + to
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService.createTextOutput(JSON.stringify({
    status: "ok",
    service: "CarePath Email Dispatcher Active"
  })).setMimeType(ContentService.MimeType.JSON);
}
