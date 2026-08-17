<?php
require_once __DIR__ . '/partials/header.php';
$services = ['Website design', 'Brand systems', 'Campaign launches'];
?>
<main class="hero">
  <p class="eyebrow">Northstar Studio</p>
  <h1>Ideas with a clear direction.</h1>
  <p>We build focused digital identities for growing companies.</p>
  <a class="button" href="contact.php">Start a project</a>
</main>
<section class="services">
  <h2>What we do</h2>
  <?php foreach ($services as $service): ?>
    <article><?php echo htmlspecialchars($service); ?></article>
  <?php endforeach; ?>
</section>
<?php require __DIR__ . '/partials/footer.php'; ?>
