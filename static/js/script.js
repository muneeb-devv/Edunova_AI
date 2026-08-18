document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.flash').forEach((el) => {
        setTimeout(() => {
            el.style.transition = 'opacity 0.4s ease';
            el.style.opacity = '0';
            setTimeout(() => el.remove(), 400);
        }, 4500);
    });
});

function togglePasswordVisibility(btn) {
    const field = btn.closest('.password-field');
    const input = field.querySelector('input');
    const isPassword = input.type === 'password';
    input.type = isPassword ? 'text' : 'password';
    field.querySelector('.eye-open').style.display = isPassword ? 'none' : 'block';
    field.querySelector('.eye-closed').style.display = isPassword ? 'block' : 'none';
    btn.setAttribute('aria-label', isPassword ? 'Hide password' : 'Show password');
}
