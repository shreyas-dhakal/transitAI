<?php
require_once __DIR__ . '/partials/header.php';
$sent = false;
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $name = trim($_POST['name'] ?? '');
    $email = trim($_POST['email'] ?? '');
    $message = trim($_POST['message'] ?? '');
    if ($name && filter_var($email, FILTER_VALIDATE_EMAIL) && $message) {
        $sent = mail('studio@example.com', 'Project request', $message, "From: $email");
    }
}
?>
<main class="contact">
  <p class="eyebrow">Contact</p>
  <h1>Tell us what you are building.</h1>
  <?php if ($sent): ?><p>Thank you. We will be in touch.</p><?php endif; ?>
  <form method="post">
    <label>Name <input name="name" required></label>
    <label>Email <input name="email" type="email" required></label>
    <label>Project <textarea name="message" required></textarea></label>
    <button type="submit">Send request</button>
  </form>
</main>
<?php require __DIR__ . '/partials/footer.php'; ?>
