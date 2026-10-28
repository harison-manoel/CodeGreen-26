/**
 * AGROHACK 2026/2 - IFRO Campus Ariquemes
 * AgroInsight — Sistema Inteligente de Gestão de Insumos Rurais
 * Script principal de interações, modais, validação dinâmica de estoque e gráficos Chart.js.
 */

document.addEventListener('DOMContentLoaded', function () {
    initMobileMenu();
    initModals();
    initMovementValidation();
    initDashboardCharts();
});

/* 1. Menu Mobile */
function initMobileMenu() {
    const toggleBtn = document.querySelector('.mobile-menu-btn');
    const sidebar = document.querySelector('.app-sidebar');

    if (toggleBtn && sidebar) {
        toggleBtn.addEventListener('click', function () {
            sidebar.classList.toggle('open');
        });

        // Fechar ao clicar fora
        document.addEventListener('click', function (e) {
            if (sidebar.classList.contains('open') && !sidebar.contains(e.target) && !toggleBtn.contains(e.target)) {
                sidebar.classList.remove('open');
            }
        });
    }
}

/* 2. Controle de Modais */
function initModals() {
    // Abrir modais
    document.querySelectorAll('[data-modal-target]').forEach(trigger => {
        trigger.addEventListener('click', function (e) {
            e.preventDefault();
            const modalId = this.getAttribute('data-modal-target');
            const modal = document.getElementById(modalId);
            if (modal) {
                modal.classList.add('show');
            }
        });
    });

    // Fechar modais
    document.querySelectorAll('.modal-close, [data-modal-close]').forEach(btn => {
        btn.addEventListener('click', function () {
            const modal = this.closest('.modal-backdrop');
            if (modal) {
                modal.classList.remove('show');
            }
        });
    });

    // Fechar ao clicar no backdrop escuro
    document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
        backdrop.addEventListener('click', function (e) {
            if (e.target === this) {
                this.classList.remove('show');
            }
        });
    });
}

/* 3. Validação Dinâmica de Saldo em Tempo Real no Registro de Movimentação */
function initMovementValidation() {
    const movForm = document.getElementById('form-registrar-movimentacao');
    if (!movForm) return;

    const selectProduto = movForm.querySelector('select[name="produto_id"]');
    const selectTipo = movForm.querySelector('select[name="tipo"]');
    const inputQtd = movForm.querySelector('input[name="quantidade"]');
    const submitBtn = movForm.querySelector('button[type="submit"]');
    const feedbackMsg = document.getElementById('mov-saldo-feedback');

    function checkBalance() {
        if (!selectProduto || !selectTipo || !inputQtd || !feedbackMsg) return;

        const selectedOption = selectProduto.options[selectProduto.selectedIndex];
        if (!selectedOption || !selectedOption.value) {
            feedbackMsg.innerHTML = '';
            submitBtn.disabled = false;
            return;
        }

        const saldoAtual = parseFloat(selectedOption.getAttribute('data-saldo') || '0');
        const unidade = selectedOption.getAttribute('data-unidade') || '';
        const tipo = selectTipo.value;
        const qtdSolicitada = parseFloat(inputQtd.value || '0');

        if (tipo === 'saida') {
            feedbackMsg.style.display = 'block';
            if (qtdSolicitada > saldoAtual) {
                feedbackMsg.className = 'form-hint alert-erro';
                feedbackMsg.style.padding = '0.5rem';
                feedbackMsg.style.borderRadius = '6px';
                feedbackMsg.style.marginTop = '0.4rem';
                feedbackMsg.innerHTML = `<strong>Bloqueio de Saldo:</strong> A quantidade solicitada (${qtdSolicitada} ${unidade}) é SUPERIOR ao saldo disponível (${saldoAtual} ${unidade}).`;
                submitBtn.disabled = true;
            } else if (qtdSolicitada > 0) {
                const saldoRestante = (saldoAtual - qtdSolicitada).toFixed(1);
                feedbackMsg.className = 'form-hint alert-sucesso';
                feedbackMsg.style.padding = '0.5rem';
                feedbackMsg.style.borderRadius = '6px';
                feedbackMsg.style.marginTop = '0.4rem';
                feedbackMsg.innerHTML = `Saldo disponível: <strong>${saldoAtual} ${unidade}</strong>. Novo saldo projetado após saída: <strong>${saldoRestante} ${unidade}</strong>.`;
                submitBtn.disabled = false;
            } else {
                feedbackMsg.className = 'form-hint';
                feedbackMsg.innerHTML = `Saldo disponível em estoque: <strong>${saldoAtual} ${unidade}</strong>.`;
                submitBtn.disabled = false;
            }
        } else {
            feedbackMsg.style.display = 'block';
            feedbackMsg.className = 'form-hint';
            feedbackMsg.innerHTML = `Saldo atual: <strong>${saldoAtual} ${unidade}</strong>. Uma entrada aumentará a quantidade armazenada.`;
            submitBtn.disabled = false;
        }
    }

    if (selectProduto) selectProduto.addEventListener('change', checkBalance);
    if (selectTipo) selectTipo.addEventListener('change', checkBalance);
    if (inputQtd) inputQtd.addEventListener('input', checkBalance);
}

/* 4. Gráficos do Dashboard com Chart.js */
function initDashboardCharts() {
    const ctxCategorias = document.getElementById('chart-categorias');
    const ctxFluxo = document.getElementById('chart-fluxo-movimentacoes');

    if (!ctxCategorias && !ctxFluxo) return;

    // Buscar dados reais calculados da API
    fetch('/api/dashboard-charts')
        .then(response => response.json())
        .then(data => {
            // A. Gráfico de Distribuição por Categoria
            if (ctxCategorias && data.categorias && data.categorias.labels.length > 0) {
                new Chart(ctxCategorias, {
                    type: 'doughnut',
                    data: {
                        labels: data.categorias.labels,
                        datasets: [{
                            data: data.categorias.data,
                            backgroundColor: [
                                '#2d6a4f', '#40916c', '#52b788', '#74c69d',
                                '#e7a73f', '#ea580c', '#0284c7', '#6366f1'
                            ],
                            borderWidth: 2,
                            borderColor: '#ffffff'
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'bottom',
                                labels: {
                                    boxWidth: 12,
                                    font: { size: 11, family: 'Inter' }
                                }
                            }
                        },
                        cutout: '65%'
                    }
                });
            }

            // B. Gráfico de Fluxo de Entradas vs Saídas
            if (ctxFluxo && data.fluxo_mensal) {
                new Chart(ctxFluxo, {
                    type: 'bar',
                    data: {
                        labels: data.fluxo_mensal.labels,
                        datasets: [
                            {
                                label: 'Entradas (Vol.)',
                                data: data.fluxo_mensal.entradas,
                                backgroundColor: '#52b788',
                                borderRadius: 6
                            },
                            {
                                label: 'Saídas (Vol.)',
                                data: data.fluxo_mensal.saidas,
                                backgroundColor: '#ea580c',
                                borderRadius: 6
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: {
                            y: {
                                beginAtZero: true,
                                grid: { color: '#f1f5f9' },
                                ticks: { font: { family: 'Inter' } }
                            },
                            x: {
                                grid: { display: false },
                                ticks: { font: { family: 'Inter' } }
                            }
                        },
                        plugins: {
                            legend: {
                                position: 'top',
                                labels: { font: { family: 'Inter', size: 12 } }
                            }
                        }
                    }
                });
            }
        })
        .catch(err => {
            console.error('Falha ao carregar métricas dos gráficos:', err);
        });
}

/* 5. Acionador de Impressão / PDF */
function triggerPrintReport() {
    window.print();
}
