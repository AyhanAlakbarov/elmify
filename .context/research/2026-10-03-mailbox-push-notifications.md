# Mailbox push notifications: Gmail `users.watch` and Microsoft Graph change notifications

Date: 2026-10-03. Serves the decision whether `sync_mailboxes` (hourly poll) should be replaced or supplemented by provider push.

**Method.** Every page below was fetched live with scrapling `get` and the quotes were copied from that output. Sources are only Google's own docs (developers.google.com/workspace/gmail, cloud.google.com / docs.cloud.google.com/pubsub) and Microsoft Learn (learn.microsoft.com/graph). No search engine was needed, because the question named its own primary sources. No tool was missing. Two Pub/Sub URLs on cloud.google.com redirect to docs.cloud.google.com, so the citations use the redirected URL.

## Answer first

- **Gmail:** push works at **both** our tiers. `users.watch` and `history.list` each accept `gmail.metadata` as well as `gmail.readonly`. It needs a Pub/Sub topic in the **same Google Cloud project as our OAuth client**. That project already exists, because the OAuth client lives in it. It also needs a push subscription pointed at a public HTTPS endpoint that checks Google's OIDC JWT, plus a daily `watch` renewal. Google itself says to keep a fallback `history.list` poll.
- **Microsoft Graph:** push works at **both** tiers, for **work/school and personal accounts alike**. `Mail.ReadBasic` and `Mail.Read` are each listed for the `message` resource in both delegated columns. It needs a public HTTPS `notificationUrl` (and ideally a `lifecycleNotificationUrl`) that answers the validation handshake within 10 s and every notification within 3 s. A subscription lasts at most 10,080 minutes (under 7 days), so a renewal job is required. Microsoft says to resync with delta query after `missed` or `subscriptionRemoved` events.
- **Recommendation (detail at the end):** push as the trigger and a periodic sync kept as a backstop, because both vendors state that notifications can be delayed or dropped. The backstop can then run much less often than "the only path" would, for example every 6 hours rather than hourly.

---

## Gmail (users.watch + Cloud Pub/Sub)

### 1. Is `users.watch` permitted with `gmail.metadata`? With `gmail.readonly`?

Yes to both. The `users.watch` reference lists four accepted scopes: `mail.google.com`, `gmail.modify`, `gmail.readonly` and `gmail.metadata`.[^g1] Either of our tiers can therefore call `watch`.

### 2. What a notification carries, and how the new mail is read

The Pub/Sub message's `data` field decodes to a JSON object holding only the email address and the new mailbox history ID.[^g2] The guide then says to call `history.list` from the last known `historyId`.[^g3]

`history.list` lists the same four scopes, including `gmail.metadata`, so the METADATA tier can read the change.[^g4] `history.list` returns only message IDs. Its records "will typically only have id and threadId fields populated", so a `messages.get` call still follows for each message.[^g5]

A stale `startHistoryId` returns 404. In that case the app "should perform a full sync".[^g6] Google says a historyId is "typically valid for at least a week, but in some rare circumstances may be valid for only a few hours".[^g6b]

### 3. Watch expiry and renewal

- `watch` must be called at least once every 7 days, or updates stop for that user.[^g7]
- Google recommends calling it once per day.[^g8]
- The response's `expiration` field is the time "when Gmail will stop sending notifications". Call `watch` again before then.[^g9]

**What happens when a watch lapses.** Notifications simply stop. The docs describe no lapse event or callback that we found, so the system detects a lapse only through the renewal job and the backstop poll. (That there is no lapse signal is **Unverified**: we did not find one, which is not proof that none exists.)

### 4. Delivery guarantees and rate limit

- **Rate limit:** each watched user is limited to one notification per second, and notifications beyond that rate are dropped.[^g10]
- **Delays and drops:** Pub/Sub usually delivers within seconds, but "in rare situations, notifications might be delayed or dropped".[^g11]
- **Google's fallback guidance:** keep a periodic `history.list` call for any user who has gone a while with no notifications.[^g12]
- **Acknowledgement:** an unacknowledged notification, such as one where the webhook errors or times out, is retried later by Pub/Sub.[^g13] A push endpoint acknowledges by returning 102, 200, 201, 202 or 204.[^g14]

### 5. Pub/Sub setup, endpoint authentication, the GCP project, pricing

- **Publish grant:** the topic must grant publish rights to `gmail-api-push@system.gserviceaccount.com`.[^g15]
- **Topic must be in our own project:** the project part of `topicName` must exactly match the Google developer project ID that makes the `watch` call.[^g16] So a GCP project is unavoidable even though we run on AWS. In practice it is the same project that already holds our Gmail OAuth client (an inference from that rule, not a separate documented statement).
- **Push endpoint requirements:** the endpoint must be a publicly accessible HTTPS address with a valid certificate signed by a certificate authority.[^g17] Pub/Sub does not verify that we own the endpoint domain.[^g18]
- **Authenticating the push:** with authentication enabled, Pub/Sub signs a JWT and sends it in the push request's authorization header.[^g19] To validate it, check the signature and confirm the token's `email` and `audience` claims match the subscription's configuration.[^g20] Google's samples also say to require `email_verified` = true.[^g21] Tokens may be up to an hour old.[^g22] The push-auth service account must be in the same project as the subscription.[^g23]
- **Pricing:**
  - The first 10 GiB of throughput each calendar month is free. After that it costs $40 per TiB.[^g24]
  - Each request is billed at a minimum of 1 KB.[^g25] Each Gmail notification is a small JSON object, so a pilot sits well inside the free tier. (That is arithmetic on the 1 KB minimum, not a quote.)
- **Domain-restricted sharing:** an organisation's domain-restricted sharing policy can block the publish grant. Google says to add an exception for the service account.[^g26] Our GCP project is not under such an organisation as far as this research knows, so this is a "check if it fails" item.

### 6. Does `watch` add a verification requirement?

No source says it does. The scopes `watch` accepts are the same restricted scopes we already request.[^g1]

- `gmail.metadata` and `gmail.readonly` are both listed under **Restricted scopes**.[^g27]
- Storing or sending restricted-scope data on servers triggers a security assessment.[^g28]

That push adds **no further** verification step beyond the restricted-scope review is **Unverified**: no page we fetched mentions one, but no page explicitly rules one out either.

---

## Microsoft Graph change notifications

### 7. Can a delegated subscription on Inbox messages be created with `Mail.ReadBasic`? With `Mail.Read`?

Yes to both. On the "Create subscription" page, the `message` row reads `Mail.ReadBasic, Mail.Read` under work/school delegated, `Mail.ReadBasic, Mail.Read` under personal delegated, and `Mail.Read` under application.[^m1] The Outlook change-notifications page lists `Mail.ReadBasic, Mail.Read` in all three columns.[^m2]

Microsoft's own prose is looser: "to get change notifications for messages, your app needs the Mail.Read permission".[^m3] That sentence gives an example, while the permissions table on the same page gives the least-privileged scope. The table is the stronger source, and it lists `Mail.ReadBasic`. Note that Microsoft says creating **and managing** a subscription needs a read scope on the resource.[^m4]

The supported paths include `/me/mailFolders('inbox')/messages` and `/me/messages`.[^m5]

**Backstop under METADATA:** delta query on messages lists `Mail.ReadBasic` as least privileged for both work/school and personal delegated access.[^m6]

### 8. Personal Microsoft accounts (Outlook.com) as well as work/school?

Yes. The `message` row has a separate "Delegated (personal Microsoft account)" column, and it lists `Mail.ReadBasic, Mail.Read`.[^m1]

For contrast, the `user` resource row explicitly says "Not supported for personal Microsoft accounts like outlook.com".[^m7] The `message` row carries no such exclusion.

Separately, change notifications as a feature are not supported in Entra External ID external tenants or Azure AD B2C tenants.[^m8] University M365 tenants are ordinary workforce tenants, so this exclusion should not apply to them (inference).

### 9. Maximum lifetime and renewal

- **Basic subscriptions:** Outlook `message`, `event` and `contact` subscriptions last at most 10,080 minutes (under seven days).[^m9]
- **Rich subscriptions:** a subscription that includes resource data lasts at most 1,440 minutes (under one day).[^m10]
- **Renewal:** an app renews with `PATCH /subscriptions/{id}` and a new `expirationDateTime`.[^m11] Without renewal it has to create a new subscription.[^m12]
- **Minimum:** any `expirationDateTime` under 45 minutes from the request is automatically set to 45 minutes.[^m13]

### 10. Endpoint requirements

- **Public HTTPS:** "If your endpoint isn't publicly accessible, Microsoft Graph doesn't send notifications to your endpoint."[^m14]
- **Validation handshake:** within 10 seconds, the endpoint must reply 200 OK with content type `text/plain` and the URL-decoded validation token in the body.[^m15] If validation fails, Graph does not create the subscription.[^m16] When a lifecycle URL is given, it is validated too.[^m17]
- **clientState:** the sources disagree. The webhooks guide says "The clientState property is required."[^m18] The `subscription` resource reference calls it "Optional", with a 128-character maximum.[^m19] Both are Microsoft's own pages. Since the webhooks guide is the one about receiving notifications, treat clientState as required. On every notification, check it matches the value sent at creation, and treat a mismatch as not genuine.[^m20]
- **Response time:** Graph counts a notification as delivered when it gets a 2xx response within 3 seconds.[^m21] The recommended pattern is to persist the notification to a queue and return `202 Accepted` inside that window.[^m22] On a non-2xx response or a timeout, Graph retries for up to 4 hours.[^m23]
- **Slow endpoints:** Graph marks an endpoint "slow" when more than 10% of its responses take over 3 seconds in a 10-minute window. New notifications then go out 10 minutes late.[^m24] It marks an endpoint "drop" when more than 15% of responses take over 10 seconds, and then drops notifications for 10 minutes.[^m25] "Dropped notifications can't be recovered."[^m26]

### 11. Payload: basic versus rich

- **Basic notifications** carry no resource data beyond the `id` of the changed resource.[^m27] A `message` notification gives the `resource` and `@odata.id`, which the app then uses to GET the message.[^m28]
- **Rich notifications are available for messages.** Outlook `contact`, `event` and `message` support subscriptions "with or without resource data".[^m29] A rich subscription requires `includeResourceData: true`, a `$select` on the resource, and an `encryptionCertificate` (public key only).[^m30] The `$select` must not include `Body` or `UniqueBody`.[^m31]
- **Permissions:** the Outlook permission table does not separate basic from rich subscriptions, and both scopes are listed for `message`.[^m2] **Unverified:** whether a rich notification under `Mail.ReadBasic` may `$select` `bodyPreview`, given that `Mail.ReadBasic` excludes body content. No page we fetched settles it.
- **Cost of rich:** the shorter 1,440-minute lifetime[^m10] plus certificate management.

### 12. Lifecycle notifications

- **Support for messages:** `reauthorizationRequired` applies to every resource. `subscriptionRemoved` and `missed` apply to Outlook `message`, `event` and personal `contact`, plus Teams `chatMessage` for `subscriptionRemoved`.[^m32]
- **Must be set at creation:** a `lifecycleNotificationUrl` cannot be added to an existing subscription by updating it. The subscription has to be deleted and recreated.[^m33]
- **reauthorizationRequired:** Graph sends this before the access token expires, before the subscription expires, or after an admin revokes the app's permission.[^m34] The app responds with `POST /subscriptions/{id}/reauthorize`, or with a `PATCH` that reauthorizes and renews in one call.[^m35] It must not send both within 10 minutes of each other.[^m36] If nobody acts, delivery eventually pauses. Changes made during the pause are lost and have to be fetched separately, for example with delta query.[^m37]
- **subscriptionRemoved:** Graph has removed the subscription, and the app must recreate it.[^m38] After recreating it, sync with delta query to find missed changes.[^m39]
- **missed:** some notifications were not delivered, for example because of throttling.[^m40] The app should do a full resync, for example with delta query.[^m41]
- **Is a lifecycle URL required?** Only for Teams resources whose expiration is more than 1 hour away. It is optional otherwise, so it is optional for mail.[^m42] Microsoft still says Outlook resources need lifecycle notifications to recover from removed subscriptions and missed notifications.[^m43] It is optional in the API but needed in practice.

### 13. Microsoft on delivery guarantees

- Microsoft says the service "might begin to drop notifications" when an endpoint is slow to respond, and that dropped notifications cannot be recovered.[^m26]
- Throttling "might include dropping notifications in a way that they can't be recovered".[^m44]
- Recovery from both `missed` and `subscriptionRemoved` events is a delta-query resync.[^m41][^m39]
- Mail notifications typically arrive in under a minute and at most within 3 minutes.[^m45]

### 14. Quotas

- **Per mailbox:** at most 1,000 active Outlook subscriptions per mailbox, counted across all applications.[^m46] We need one per student.
- **Duplicates:** a subscription with the same `changeType` and `resource` as an existing one fails with 409 Conflict.[^m47]
- **Exceeding a quota** returns 403 Forbidden.[^m48]
- **No per-app Outlook quota** appears in the table. The 50,000 per-app limit shown there applies to `user`/`group` only.[^m49]

---

## Synthesis

| | Gmail METADATA (`gmail.metadata`) | Gmail CONTENT (`gmail.readonly`) | Graph METADATA (`Mail.ReadBasic`) | Graph CONTENT (`Mail.Read`) |
|---|---|---|---|---|
| Push feasible | Yes (watch + history.list allow it) | Yes | Yes (basic notifications; work/school + personal) | Yes (basic or rich) |
| Payload | emailAddress + historyId only | same | message id only | id only (basic), or encrypted `$select` fields (rich, 1-day lifetime) |
| Renewal | `watch` daily (hard limit 7 days) | same | `PATCH` before 10,080 min (under 7 days) | same; under 1 day if rich |
| Backstop read | `history.list` (404 → full sync) | same | `/messages/delta` (`Mail.ReadBasic` least privileged) | same |

**New infrastructure, both providers together:**

1. **Two public webhook routes on the existing HTTPS load balancer.**
   - A Pub/Sub push route that verifies the Google OIDC JWT (signature, `aud`, `email`, `email_verified`).
   - A Graph route for notifications and lifecycle events. It answers the validation-token handshake, checks clientState, and returns 202 within 3 s after enqueueing.
   - Neither route can do mailbox work inline: Graph's 3-second window and its slow/drop states make that unsafe.
2. **A Google Cloud setup in the project that already holds the Gmail OAuth client:**
   - one topic with publish rights for `gmail-api-push@system.gserviceaccount.com`
   - one push subscription with authentication enabled
   - one push-auth service account
   - Pub/Sub enabled on that project
   - Whether this needs a billing account attached is **Unverified**.
3. **Per-mailbox state:** Gmail `historyId` and watch `expiration`; Graph subscription id, `expirationDateTime`, clientState and delta link.
4. **A periodic job that still has to exist.** It does three things:
   - renews every Gmail watch (daily)
   - renews every Graph subscription (well before 7 days)
   - runs the backstop sync (`history.list` and `messages/delta`) for mailboxes that have been quiet.

   This is `sync_mailboxes` run at a lower frequency, plus a renew step. It is not deleted.

**Recommendation.** Use push as the primary trigger and keep `sync_mailboxes` as a backstop. Both providers support push at our METADATA tier for every pilot account type: Gmail `watch`/`history.list` accept `gmail.metadata`,[^g1][^g4] and Graph lists `Mail.ReadBasic` for `message` subscriptions in both delegated columns.[^m1]

Both providers also say push alone is not enough:

- Google: "notifications might be delayed or dropped", and fall back to periodic `history.list`.[^g11][^g12]
- Microsoft: "Dropped notifications can't be recovered", and recover through delta query after `missed` or `subscriptionRemoved` events.[^m26][^m41]

So the job stays, with two duties: renewals (Gmail daily,[^g8] Graph under 7 days[^m9]) and a backstop sync. Because push now covers the normal case, the backstop can drop from hourly to about every 6 hours. The extension's on-demand check stays as the student's manual "check now".

Build Graph first. It needs no new cloud account, it covers the pilot's Outlook.com and university M365 users today, and it is the one that needs the lifecycle URL from day one, since that URL cannot be added later.[^m33] Gmail push can wait until Gmail leaves Testing status and passes verification, because it changes nothing about that review.

Use basic notifications, not rich ones. Rich would mean a certificate, encryption and a 1-day lifetime[^m10] to save one GET per message.

The 6-hour figure is a judgement, not a sourced number. It is bounded by Gmail's "historyId may be valid for only a few hours" warning,[^g6b] since a backstop slower than that risks forced full syncs.

## Open questions

- **Rich Graph notifications under `Mail.ReadBasic`:** can `$select` include `bodyPreview`? Unverified. Basic notifications avoid the question.
- **Gmail `watch` and verification:** does it add anything to the restricted-scope verification? No source says so either way. Unverified.
- **Pub/Sub billing account:** does the GCP project need one attached to create a topic, even inside the free tier? Not checked. Unverified.
- **Gmail watch lapse:** is there any signal when a watch lapses? None found in the docs. Detection relies on our own `expiration` tracking.
- **Microsoft's `missed` lifecycle event:** it covers drops the service knows about. Whether it fires for every drop, including the "drop" throttling state, is not stated. Keep the backstop either way.

## Sources

[^g1]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/watch "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.metadata"
[^g2]: https://developers.google.com/workspace/gmail/api/guides/push "Base64URL-encoded string that decodes to a JSON object containing the email address and the new mailbox history ID for the user"
[^g3]: https://developers.google.com/workspace/gmail/api/guides/push "You can then use the history.list method to get the change details for the user since their last known historyId"
[^g4]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.metadata"
[^g5]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list "Any messages contained in the response will typically only have id and threadId fields populated."
[^g6]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list "If you receive an HTTP 404 error response, your application should perform a full sync."
[^g6b]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list "A historyId is typically valid for at least a week, but in some rare circumstances may be valid for only a few hours."
[^g7]: https://developers.google.com/workspace/gmail/api/guides/push "You must call the watch method at least once every 7 days or you'll stop receiving updates for the user."
[^g8]: https://developers.google.com/workspace/gmail/api/guides/push "We recommend calling watch once per day."
[^g9]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/watch "When Gmail will stop sending notifications for mailbox updates (epoch millis)."
[^g10]: https://developers.google.com/workspace/gmail/api/guides/push "Each Gmail user being watched has a maximum notification rate of one event per second. The service drops any user notifications exceeding that rate."
[^g11]: https://developers.google.com/workspace/gmail/api/guides/push "However, in rare situations, notifications might be delayed or dropped."
[^g12]: https://developers.google.com/workspace/gmail/api/guides/push "fall back to periodically calling the history.list method after a period with no notifications for a user"
[^g13]: https://developers.google.com/workspace/gmail/api/guides/push "Cloud Pub/Sub retries the notification at a later time."
[^g14]: https://docs.cloud.google.com/pubsub/docs/push "To acknowledge the message, return one of the following status codes"
[^g15]: https://developers.google.com/workspace/gmail/api/guides/push "grant publish privileges to gmail-api-push@system.gserviceaccount.com"
[^g16]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/watch "must exactly match your Google developer project id (the one executing this watch request)"
[^g17]: https://docs.cloud.google.com/pubsub/docs/create-push-subscription "The server for the push endpoint must have a valid SSL certificate signed by a certificate authority."
[^g18]: https://docs.cloud.google.com/pubsub/docs/create-push-subscription "Pub/Sub doesn't require proof of ownership for push subscription URL domains."
[^g19]: https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions "signs a JSON Web Token (JWT) and sends the JWT in the authorization header of the push request"
[^g20]: https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions "Ensuring that the email and audience claims in the token match the values set in the push subscription configuration."
[^g21]: https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions "Ensure that `payload.Email_verified` is set to true."
[^g22]: https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions "The tokens attached to requests sent to push endpoints may be up to an hour old."
[^g23]: https://docs.cloud.google.com/pubsub/docs/create-push-subscription "must be in the same project as the push subscription"
[^g24]: https://cloud.google.com/pubsub/pricing "the first 10 GiB of throughput identified as the Message Delivery Basic SKU for a billing account is free"
[^g25]: https://cloud.google.com/pubsub/pricing "A minimum of 1 KB is assessed for each request, independent of the message sizes in the request."
[^g26]: https://developers.google.com/workspace/gmail/api/guides/push "domain-restricted sharing configuration might prevent you from granting publish permissions"
[^g27]: https://developers.google.com/workspace/gmail/api/auth/scopes "View your email message metadata such as labels and headers, but not the email body."
[^g28]: https://developers.google.com/workspace/gmail/api/auth/scopes "If you store restricted scope data on servers (or transmit), then you must go through a security assessment."
[^m1]: https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0 "message Mail.ReadBasic, Mail.Read Mail.ReadBasic, Mail.Read Mail.Read"
[^m2]: https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview "Mail.ReadBasic, Mail.Read Mail.ReadBasic, Mail.Read Mail.ReadBasic, Mail.Read"
[^m3]: https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0 "to get change notifications for messages, your app needs the Mail.Read permission"
[^m4]: https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview "Creating and managing (getting, updating, and deleting) a subscription requires a read scope to the resource."
[^m5]: https://learn.microsoft.com/en-us/graph/change-notifications-overview "Changes to messages in a user's Inbox"
[^m6]: https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0 "Delegated (personal Microsoft account) Mail.ReadBasic"
[^m7]: https://learn.microsoft.com/en-us/graph/change-notifications-overview "Not supported for personal Microsoft accounts like outlook.com."
[^m8]: https://learn.microsoft.com/en-us/graph/change-notifications-overview "The change notifications feature isn't supported in Microsoft Entra External ID in external tenants and Azure AD B2C tenants."
[^m9]: https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0 "10,080 minutes (under seven days)"
[^m10]: https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0 "For subscriptions with resource data (rich notification subscriptions), subscription lifetime is 1440 minutes (under one day)."
[^m11]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "The simplest way to continue receiving notifications is to continue renewing your subscription request."
[^m12]: https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0 "Apps need to renew their subscriptions before the expiration time; otherwise, they need to create a new subscription."
[^m13]: https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0 "Any value under 45 minutes after the time of the request is automatically set to 45 minutes after the request time."
[^m14]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "If your endpoint isn't publicly accessible, Microsoft Graph doesn't send notifications to your endpoint."
[^m15]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "The client must respond with the following characteristics within 10 seconds of step 1"
[^m16]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "If the endpoint validation fails, Microsoft Graph doesn't create the subscription."
[^m17]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "the subscription service also validates the lifecycleNotificationUrl"
[^m18]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "The clientState property is required."
[^m19]: https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0 "Optional. Specifies the value of the clientState property sent by the service in each change notification. The maximum length is 128 characters."
[^m20]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "If there's a mismatch, don't consider the change notification as valid."
[^m21]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "receives a 2xx HTTP response from your endpoint within 3 seconds, the notification is considered delivered"
[^m22]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "validate and persist the notification in a queue on your endpoint and return 202 Accepted status code within the 3-second window"
[^m23]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "it continues to retry delivery for up to 4 hours"
[^m24]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "any new notifications are sent on after a 10-minute delay"
[^m25]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "notifications are dropped for a 10-minute window"
[^m26]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "If an endpoint doesn't respond in a timely manner, the change notification service might begin to drop notifications. Dropped notifications can't be recovered."
[^m27]: https://learn.microsoft.com/en-us/graph/change-notifications-overview "Change notifications that don't contain resource data other than the id of the resource that changed."
[^m28]: https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview "Use the resource and @odata.id properties to make calls to Microsoft Graph to get the payload of the resource."
[^m29]: https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview "The following Outlook resources support subscriptions with or without resource data in the change notification payload."
[^m30]: https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview "This property contains only the public key that Microsoft Graph uses to encrypt resource data."
[^m31]: https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview "Do not include in the URL $top, $skip, $orderby, $select=Body,UniqueBody"
[^m32]: https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events "missed notifications - Outlook"
[^m33]: https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events "You also can't add the lifecycleNotificationUrl property to an existing subscription by updating the subscription."
[^m34]: https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events "When an administrator has revoked your app's permissions to read a resource."
[^m35]: https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events "Perform the update operation to reauthorize and renew the subscription at the same time."
[^m36]: https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events "for the same subscription within a 10-minute window"
[^m37]: https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events "In such cases, the app should separately fetch those changes, for example using the delta query."
[^m38]: https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events "if you want to continue receiving change notifications for the related resource, you need to recreate the subscription"
[^m39]: https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events "After creating the new subscription, you can sync the resource data to identify any missed change notifications; for example using the delta query."
[^m40]: https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events "lifecycle events alert you that some change notifications weren't delivered."
[^m41]: https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events "Perform a full data resync of the resource to identify the changes that weren't delivered as notifications; for example, using the delta query."
[^m42]: https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0 "Required for Teams resources if the expirationDateTime value is more than 1 hour from now; optional otherwise."
[^m43]: https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview "Lifecycle notifications are needed in case your app gets their subscriptions removed or misses some change notifications."
[^m44]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "It might include dropping notifications in a way that they can't be recovered."
[^m45]: https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0 "message Less than 1 minute 3 minutes"
[^m46]: https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview "There is a maximum limit of 1000 active subscriptions for Outlook resources per mailbox for all applications."
[^m47]: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks "the request fails with an HTTP error code 409 Conflict"
[^m48]: https://learn.microsoft.com/en-us/graph/change-notifications-overview "When exceeding that limit, attempts to create a subscription will result in a 403 Forbidden error response."
[^m49]: https://learn.microsoft.com/en-us/graph/change-notifications-overview "Per app (for all tenants combined): 50,000 total subscriptions."
