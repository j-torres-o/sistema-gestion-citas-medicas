/* ============================================================================
   ARCHIVO: static/js/app.js
   PROPÓSITO: Lógica Single Page Application (SPA) para el SGCM.
   Gestiona estado global, ruteo asíncrono en DOM, integraciones RESTful API,
   asistencia accesible por voz mediante Web Speech API y buscadores reactivos.
   ============================================================================ */

// 1. ESTADO GLOBAL DE LA APLICACIÓN
const state = {
    session: null,           // Datos de sesión del usuario autenticado
    activeView: 'login-view', // Vista activa actual
    theme: 'claro',         // Tema visual: 'claro', 'oscuro', 'contraste'
    
    // Datos y catálogos en caché
    branches: [],
    specialties: [],
    doctors: [],
    receptionists: [],
    
    // Estado del Wizard de Paciente
    wizard: {
        step: 1,
        selectedSpecialty: null,
        selectedCity: null,      // Para selección en dos pasos (Ciudad ➔ Sede)
        selectedBranch: null,
        selectedSlot: null,
        availableSlots: []
    },
    
    // Asistencia por voz (Web Speech API)
    speech: {
        synthesisActive: false,
        recognitionActive: false,
        recognition: null
    },
    
    // Estado del Dashboard Médico
    medico: {
        selectedAppointment: null,
        waitingRoomInterval: null
    },
    
    // Intervalo de actualización del Recepcionista
    receptionist: {
        refreshInterval: null
    }
};

// 2. INICIALIZACIÓN GENERAL DEL DOM
document.addEventListener('DOMContentLoaded', () => {
    // Configurar tema inicial por defecto
    const savedTheme = localStorage.getItem('sgcm-theme') || 'claro';
    setTheme(savedTheme);
    
    // Inicializar Web Speech API
    initSpeechRecognition();
    
    // Pre-cargar voces asíncronas para consistencia de voz femenina
    if (window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = () => {
            getFemaleSpanishVoice();
        };
        // Intento de precarga inmediata
        getFemaleSpanishVoice();
    }
    
    // Asegurar limpieza de intervals al cerrar/recargar
    window.addEventListener('beforeunload', () => {
        clearIntervals();
    });
    
    showToast('Sistema de Gestión de Citas Médicas listo.', 'success');
});

// 3. ENRUTADOR Y NAVEGACIÓN SPA
function showView(viewId) {
    // Ocultar todos los paneles
    document.querySelectorAll('.view-panel').forEach(panel => {
        panel.classList.add('hidden');
    });
    
    // Limpiar intervalos activos de dashboards previos
    clearIntervals();
    
    // Mostrar el panel solicitado
    const activePanel = document.getElementById(viewId);
    if (activePanel) {
        activePanel.classList.remove('hidden');
        state.activeView = viewId;
    }
    
    // Disparar lógica de carga específica por panel
    if (viewId === 'patient-view') {
        loadPatientDashboard();
    } else if (viewId === 'recep-view') {
        loadReceptionistDashboard();
    } else if (viewId === 'medico-view') {
        loadMedicoDashboard();
    } else if (viewId === 'admin-view') {
        loadAdminDashboard();
    }
}

function clearIntervals() {
    if (state.medico.waitingRoomInterval) {
        clearInterval(state.medico.waitingRoomInterval);
        state.medico.waitingRoomInterval = null;
    }
    if (state.receptionist.refreshInterval) {
        clearInterval(state.receptionist.refreshInterval);
        state.receptionist.refreshInterval = null;
    }
}

// 4. AUTENTICACIÓN Y CONTROL DE ACCESO
async function loginSubmit() {
    const userField = document.getElementById('login-username');
    const passField = document.getElementById('login-password');
    const errField = document.getElementById('login-error');
    
    const username = userField.value.trim();
    const password = passField.value.trim();
    
    if (!username || !password) {
        showLoginError('Por favor ingrese su usuario y contraseña.');
        return;
    }
    
    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showLoginError(data.error || 'Fallo de autenticación.');
            return;
        }
        
        // Carga de sesión exitosa
        state.session = data.session;
        errField.classList.add('hidden');
        
        // Actualizar UI del header
        document.getElementById('session-username').innerText = `${state.session.nombre_completo} [${state.session.rol}]`;
        document.getElementById('btn-logout').classList.remove('hidden');
        
        // Enrutar al dashboard correspondiente
        showToast(`Bienvenido ${state.session.nombre_completo}`, 'success');
        
        if (state.session.rol === 'Paciente') {
            showView('patient-view');
        } else if (state.session.rol === 'Recepcionista') {
            showView('recep-view');
        } else if (state.session.rol === 'Medico') {
            showView('medico-view');
        } else if (state.session.rol === 'Admin') {
            showView('admin-view');
        }
        
        // Limpiar campos de login
        userField.value = '';
        passField.value = '';
        
    } catch (err) {
        showLoginError('Fallo en la comunicación con el servidor de autenticación.');
    }
}

function showLoginError(msg) {
    const errField = document.getElementById('login-error');
    errField.innerText = msg;
    errField.classList.remove('hidden');
    speakText(msg);
}

function logout() {
    state.session = null;
    document.getElementById('session-username').innerText = 'Sin iniciar sesión';
    document.getElementById('btn-logout').classList.add('hidden');
    
    // Desactivar voz
    if (state.speech.recognitionActive) {
        toggleMicRecord();
    }
    state.speech.synthesisActive = false;
    document.getElementById('btn-speech-assist').innerText = '[🔊 Activar Asistencia por Voz]';
    document.getElementById('btn-mic-record').classList.add('hidden');
    
    showToast('Sesión cerrada correctamente.', 'success');
    showView('login-view');
}

// 5. ASISTENCIA POR VOZ Y ACCESIBILIDAD (WEB SPEECH API)
function initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        console.warn('La API de Reconocimiento de Voz no está soportada en este navegador.');
        return;
    }
    
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.lang = 'es-ES';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    
    recognition.onstart = () => {
        state.speech.recognitionActive = true;
        document.getElementById('btn-mic-record').innerText = '[🔴 Escuchando...]';
        document.getElementById('btn-mic-record').style.backgroundColor = '#EF4444';
    };
    
    recognition.onend = () => {
        state.speech.recognitionActive = false;
        document.getElementById('btn-mic-record').innerText = '[🎙️ Dictar DNI/Siguiente]';
        document.getElementById('btn-mic-record').style.backgroundColor = '';
    };
    
    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript.trim().toLowerCase();
        console.log('[SPEECH REC] Recibido:', transcript);
        showToast(`Escuchado: "${transcript}"`, 'info');
        handleVoiceCommand(transcript);
    };
    
    recognition.onerror = (event) => {
        console.error('[SPEECH REC] Error:', event.error);
        if (event.error !== 'no-speech') {
            showToast(`Error de micrófono: ${event.error}`, 'error');
        }
    };
    
    state.speech.recognition = recognition;
}

function toggleSpeechAssist() {
    state.speech.synthesisActive = !state.speech.synthesisActive;
    const btn = document.getElementById('btn-speech-assist');
    const btnMic = document.getElementById('btn-mic-record');
    
    if (state.speech.synthesisActive) {
        btn.innerText = '[🔇 Desactivar Asistencia por Voz]';
        btn.classList.add('btn-primary');
        btnMic.classList.remove('hidden');
        speakText('Asistencia por voz activada. Te guiaré paso a paso.');
        announceWizardStep();
    } else {
        btn.innerText = '[🔊 Activar Asistencia por Voz]';
        btn.classList.remove('btn-primary');
        btnMic.classList.add('hidden');
        if (state.speech.recognitionActive) {
            toggleMicRecord();
        }
    }
}

function toggleMicRecord() {
    if (!state.speech.recognition) {
        showToast('El reconocimiento de voz no está disponible.', 'error');
        return;
    }
    
    if (state.speech.recognitionActive) {
        state.speech.recognition.stop();
    } else {
        try {
            state.speech.recognition.start();
        } catch (e) {
            console.error(e);
        }
    }
}

function getFemaleSpanishVoice() {
    if (state.speech.selectedVoice) {
        return state.speech.selectedVoice;
    }
    
    const voices = window.speechSynthesis.getVoices();
    const spanishVoices = voices.filter(voice => voice.lang.toLowerCase().includes('es-'));
    
    if (spanishVoices.length === 0) {
        return null;
    }
    
    // Lista ordenada de palabras clave femeninas comunes en motores TTS (Sabina, Helena, Lucía, María, Elena, Google, Lucia, Monica)
    const femaleKeywords = ["sabina", "helena", "lucia", "maria", "elena", "google", "samantha", "monica", "laura", "paulina"];
    
    for (let kw of femaleKeywords) {
        const matched = spanishVoices.find(voice => voice.name.toLowerCase().includes(kw));
        if (matched) {
            state.speech.selectedVoice = matched;
            console.log("[SPEECH] Consistencia de voz establecida (Femenina):", matched.name);
            return matched;
        }
    }
    
    // Fallback si no se detecta explícitamente por palabra clave
    state.speech.selectedVoice = spanishVoices[0];
    console.log("[SPEECH] Consistencia de voz establecida (Default):", spanishVoices[0].name);
    return spanishVoices[0];
}

function speakText(text) {
    if (!state.speech.synthesisActive) return;
    
    // Detener cualquier locución en curso
    window.speechSynthesis.cancel();
    
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'es-ES';
    utterance.rate = 0.85; // Velocidad pausada y comprensible para adultos mayores
    
    const femaleVoice = getFemaleSpanishVoice();
    if (femaleVoice) {
        utterance.voice = femaleVoice;
    }
    
    window.speechSynthesis.speak(utterance);
}

function handleVoiceCommand(cmd) {
    if (state.activeView === 'login-view') return;
    
    // Comandos del Wizard del Paciente
    if (state.activeView === 'patient-view') {
        // Navegación
        if (cmd.includes('siguiente') || cmd.includes('avanzar')) {
            nextWizardStep();
            return;
        }
        if (cmd.includes('anterior') || cmd.includes('regresar') || cmd.includes('atrás')) {
            prevWizardStep();
            return;
        }
        if (cmd.includes('repetir')) {
            announceWizardStep();
            return;
        }
        
        // Selección del Paso 1: Especialidad
        if (state.wizard.step === 1) {
            const specs = ['medicina general', 'pediatria', 'pediatría', 'cardiologia', 'cardiología', 'dermatologia', 'dermatología'];
            for (let spec of specs) {
                if (cmd.includes(spec)) {
                    const normSpec = spec.replace('í', 'i').replace('ó', 'o');
                    // Buscar coincidencia en specialties
                    const matched = state.specialties.find(s => normalizeText(s.nombre) === normSpec);
                    if (matched) {
                        selectSpecialty(matched.id_especialidad);
                        speakText(`Seleccionado especialidad ${matched.nombre}.`);
                        return;
                    }
                }
            }
        }
        
        // Selección del Paso 2: Sede
        if (state.wizard.step === 2) {
            for (let branch of state.branches) {
                const normName = normalizeText(branch.nombre);
                if (cmd.includes(normName) || cmd.includes(normalizeText(branch.ciudad))) {
                    selectBranch(branch.id_sede);
                    speakText(`Seleccionado sede ${branch.nombre}.`);
                    return;
                }
            }
        }
        
        // Selección del Paso 3: Horarios / Doctor
        if (state.wizard.step === 3) {
            if (cmd.includes('espera') || cmd.includes('lista')) {
                registerWaitlistSubmit();
                return;
            }
            // Elegir slots por orden numérico hablado
            const numbers = ['primero', 'segundo', 'tercero', 'cuarto', 'quinto', 'uno', 'dos', 'tres', 'cuatro', 'cinco'];
            for (let i = 0; i < numbers.length; i++) {
                if (cmd.includes(numbers[i])) {
                    const idx = i % 5; // Mapear primero a 0, uno a 0, etc.
                    if (state.wizard.availableSlots[idx]) {
                        selectSlot(state.wizard.availableSlots[idx].id_cita);
                        return;
                    }
                }
            }
        }
    }
}

function normalizeText(text) {
    return text.toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, ""); // Remover acentos
}

// 6. PORTAL DEL PACIENTE (LINEAR WIZARD PATTERN & SERVICES)
async function loadPatientDashboard() {
    state.wizard.step = 1;
    state.wizard.selectedSpecialty = null;
    state.wizard.selectedCity = null;
    state.wizard.selectedBranch = null;
    state.wizard.selectedSlot = null;
    state.wizard.availableSlots = [];
    
    // Renderizar pasos visuales
    updateWizardUI();
    
    // Cargar Catálogos Core y Listas Auxiliares de forma paralela
    try {
        const [branchesRes, specialtiesRes] = await Promise.all([
            fetch('/api/branches'),
            fetch('/api/specialties')
        ]);
        
        state.branches = await branchesRes.json();
        state.specialties = await specialtiesRes.json();
        
        renderSpecialtiesGrid();
        renderBranchesGrid();
        
        // Cargar listas del Paciente en el Sidebar
        await refreshPatientSidebarLists();
        
        if (state.speech.synthesisActive) {
            announceWizardStep();
        }
    } catch (e) {
        showToast('Error al cargar la información del portal.', 'error');
    }
}

async function refreshPatientSidebarLists() {
    if (!state.session || !state.session.id_perfil_clinico) return;
    
    try {
        const pId = state.session.id_perfil_clinico;
        const [aptsRes, authsRes, waitsRes] = await Promise.all([
            fetch(`/api/patient/appointments?id_paciente=${pId}`),
            fetch(`/api/patient/authorizations?id_paciente=${pId}`),
            fetch(`/api/patient/waitlist?id_paciente=${pId}`)
        ]);
        
        const appointments = await aptsRes.json();
        const authorizations = await authsRes.json();
        const waitlist = await waitsRes.json();
        
        renderPatientActiveAppointments(appointments);
        renderPatientMedicalAuthorizations(authorizations);
        renderPatientWaitlistRequests(waitlist);
        
    } catch (e) {
        console.error('Error al actualizar las listas del paciente:', e);
    }
}

// Renderizadores de Catálogos
function renderSpecialtiesGrid() {
    const grid = document.getElementById('specialties-options-grid');
    grid.innerHTML = '';
    
    state.specialties.forEach(spec => {
        const card = document.createElement('div');
        card.className = `option-card ${state.wizard.selectedSpecialty === spec.id_especialidad ? 'selected' : ''}`;
        card.id = `spec-card-${spec.id_especialidad}`;
        card.onclick = () => selectSpecialty(spec.id_especialidad);
        
        card.innerHTML = `
            <div class="option-card-title">${spec.nombre}</div>
            <div class="option-card-desc">${spec.descripcion || ''}</div>
        `;
        grid.appendChild(card);
    });
}

function selectCity(city) {
    state.wizard.selectedCity = city;
    renderBranchesGrid();
    speakText(`Seleccionado ciudad ${city}. Ahora elija la sede.`);
}

function selectBranch(id) {
    state.wizard.selectedBranch = id;
    renderBranchesGrid();
    
    setTimeout(() => {
        nextWizardStep();
    }, 450);
}

function renderBranchesGrid() {
    const grid = document.getElementById('branches-options-grid');
    grid.innerHTML = '';
    
    const pCity = state.session ? state.session.ciudad_origen : null;
    const pSede = state.session ? state.session.id_sede : null;
    
    // Si no se ha seleccionado ciudad, renderizar listado de ciudades
    if (!state.wizard.selectedCity) {
        // Obtener ciudades únicas
        const cities = [...new Set(state.branches.map(b => b.ciudad))];
        
        // Ordenar ciudades poniendo la del paciente de primero
        if (pCity) {
            cities.sort((a, b) => {
                const normA = normalizeText(a);
                const normB = normalizeText(b);
                const normPCity = normalizeText(pCity);
                if (normA === normPCity) return -1;
                if (normB === normPCity) return 1;
                return a.localeCompare(b);
            });
        }
        
        // Actualizar el título de la sección dinámicamente
        const header = document.querySelector('#wizard-step-2 h3');
        if (header) {
            header.innerText = 'Selecciona la Ciudad de tu Sede:';
        }
        
        cities.forEach(city => {
            const card = document.createElement('div');
            card.className = 'option-card';
            card.onclick = () => selectCity(city);
            
            // Si es la ciudad del paciente, agregar un badge de "Tu Ciudad"
            let badge = '';
            if (pCity && normalizeText(city) === normalizeText(pCity)) {
                badge = '<div class="option-card-badge">🏠 Tu Ciudad de Residencia</div>';
            }
            
            card.innerHTML = `
                <div class="option-card-title">🏢 Ciudad: ${city}</div>
                <div class="option-card-desc">Ver sedes clínicas disponibles en ${city}</div>
                ${badge}
            `;
            grid.appendChild(card);
        });
        
    } else {
        // Renderizar las sedes de la ciudad seleccionada
        const header = document.querySelector('#wizard-step-2 h3');
        if (header) {
            header.innerText = `Sedes clínicas disponibles en ${state.wizard.selectedCity}:`;
        }
        
        // Agregar botón para volver a ciudades
        const backCard = document.createElement('div');
        backCard.className = 'option-card';
        backCard.style.borderStyle = 'dashed';
        backCard.onclick = () => {
            state.wizard.selectedCity = null;
            state.wizard.selectedBranch = null;
            renderBranchesGrid();
            speakText("Regresando al listado de ciudades.");
        };
        backCard.innerHTML = `
            <div class="option-card-title">⬅️ Cambiar de Ciudad</div>
            <div class="option-card-desc">Volver a ver todas las ciudades disponibles.</div>
        `;
        grid.appendChild(backCard);
        
        // Filtrar y ordenar sedes
        let branchesInCity = state.branches.filter(b => normalizeText(b.ciudad) === normalizeText(state.wizard.selectedCity));
        
        if (normalizeText(state.wizard.selectedCity) === normalizeText(pCity)) {
            // Ordenar poniendo la sede del paciente de primero
            branchesInCity.sort((a, b) => {
                if (pSede) {
                    if (String(a.id_sede) === String(pSede)) return -1;
                    if (String(b.id_sede) === String(pSede)) return 1;
                }
                return a.nombre.localeCompare(b.nombre);
            });
        }
        
        branchesInCity.forEach(branch => {
            const card = document.createElement('div');
            card.className = `option-card ${state.wizard.selectedBranch === branch.id_sede ? 'selected' : ''}`;
            card.id = `branch-card-${branch.id_sede}`;
            card.onclick = () => selectBranch(branch.id_sede);
            
            let badge = '';
            if (pSede && String(branch.id_sede) === String(pSede)) {
                badge = '<div class="option-card-badge">🏥 Tu Sede Asignada</div>';
            }
            
            card.innerHTML = `
                <div class="option-card-title">${branch.nombre}</div>
                <div class="option-card-desc">📍 ${branch.direccion}</div>
                ${badge}
            `;
            grid.appendChild(card);
        });
    }
}

// Renderizadores de Sidebar
function renderPatientActiveAppointments(list) {
    const container = document.getElementById('patient-active-appointments');
    container.innerHTML = '';
    
    if (list.length === 0) {
        container.innerHTML = '<div class="sidebar-help">No posee citas programadas actualmente.</div>';
        return;
    }
    
    list.forEach(apt => {
        const item = document.createElement('div');
        item.className = 'list-item';
        
        let cancelBtn = '';
        // Solo permitir cancelar si es futura
        if (apt.estado === 'Agendada' || apt.estado === 'Confirmada') {
            cancelBtn = `<button class="btn btn-logout" style="margin-top: 8px; min-height:36px; height:36px; padding:2px 8px;" onclick="cancelAppointmentFromPatient('${apt.id_cita}')">[❌ Cancelar]</button>`;
        }
        
        item.innerHTML = `
            <div class="list-item-title">🩺 ${apt.especialidad_nombre} - ${apt.doctor_nombre}</div>
            <div class="list-item-meta">
                🏢 Sede: ${apt.sede_nombre}<br>
                📅 Fecha: ${apt.fecha} a las ${apt.hora_inicio} - ${apt.hora_fin}<br>
                <span>Estado: <strong class="badge badge-${apt.estado.toLowerCase()}">${apt.estado}</strong></span>
            </div>
            ${cancelBtn}
        `;
        container.appendChild(item);
    });
}

function renderPatientMedicalAuthorizations(list) {
    const container = document.getElementById('patient-medical-authorizations');
    container.innerHTML = '';
    
    if (list.length === 0) {
        container.innerHTML = '<div class="sidebar-help">Sin autorizaciones médicas vigentes.</div>';
        return;
    }
    
    list.forEach(auth => {
        const item = document.createElement('div');
        item.className = 'list-item';
        item.innerHTML = `
            <div class="list-item-title">📋 Especialidad: ${auth.especialidad_nombre}</div>
            <div class="list-item-meta">
                🩺 Emitido por: ${auth.doctor_nombre}<br>
                🔄 Sesiones: ${auth.sesiones_consumidas} de ${auth.sesiones_totales} consumidas<br>
                📅 Frecuencia: cada ${auth.frecuencia_dias} días<br>
                <span>Estado: <strong class="badge">${auth.estado}</strong></span>
            </div>
        `;
        container.appendChild(item);
    });
}

function renderPatientWaitlistRequests(list) {
    const container = document.getElementById('patient-waitlist-requests');
    container.innerHTML = '';
    
    if (list.length === 0) {
        container.innerHTML = '<div class="sidebar-help">No tiene solicitudes activas en lista de espera.</div>';
        return;
    }
    
    list.forEach(wl => {
        const item = document.createElement('div');
        item.className = 'list-item';
        
        const friendlyCola = wl.tipo_cola === 'FechaCercana' ? 'Fecha más cercana' : 'Rango de fechas específico';
        
        item.innerHTML = `
            <div class="list-item-title">⏳ Especialidad: ${wl.especialidad_nombre}</div>
            <div class="list-item-meta">
                🏢 Sede: ${wl.sede_nombre}<br>
                📅 Rango deseado: ${wl.rango_deseado}<br>
                <span>Cola: <strong>${friendlyCola}</strong><br>Estado: <strong class="badge">${wl.estado}</strong></span><br>
                <span style="font-size:10px;">Creada: ${wl.fecha_creacion}</span>
            </div>
        `;
        container.appendChild(item);
    });
}

// Lógica de Transiciones del Wizard
function selectSpecialty(id) {
    state.wizard.selectedSpecialty = id;
    renderSpecialtiesGrid();
    
    // Autocompletado de voz/avanzar
    setTimeout(() => {
        nextWizardStep();
    }, 450);
}

function selectBranch(id) {
    state.wizard.selectedBranch = id;
    renderBranchesGrid();
    
    setTimeout(() => {
        nextWizardStep();
    }, 450);
}

async function selectSlot(id_cita) {
    state.wizard.selectedSlot = id_cita;
    
    // Realizar reserva de forma atómica
    const pId = state.session.id_perfil_clinico;
    
    try {
        const response = await fetch('/api/appointments/book', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id_cita: id_cita,
                id_paciente: pId,
                realizado_por: 'Paciente',
                usuario_identificador: state.session.username
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showToast(data.error || 'Error al agendar la cita.', 'error');
            speakText(`No se pudo reservar: ${data.error || ''}`);
            return;
        }
        
        // Éxito. Renderizar Paso 4 (Confirmación)
        state.wizard.step = 4;
        updateWizardUI();
        
        const slot = state.wizard.availableSlots.find(s => s.id_cita === id_cita);
        const confirmText = `Tu cita ha sido reservada de forma consistente con el Dr. ${slot.doctor_nombre} en la sede ${slot.sede_nombre} para el día ${slot.fecha} a las ${slot.hora_inicio} horas.`;
        document.getElementById('wizard-confirm-text').innerText = confirmText;
        
        speakText('¡Excelente! Tu reserva ha sido confirmada con éxito.');
        showToast('Cita reservada con éxito de forma consistente.', 'success');
        
        // Actualizar listas del sidebar
        await refreshPatientSidebarLists();
        
    } catch (e) {
        showToast('Fallo crítico al enviar la solicitud de reserva.', 'error');
    }
}

async function loadWizardSlots() {
    const container = document.getElementById('slots-options-grid');
    container.innerHTML = '<div style="grid-column: 1/-1; text-align:center; padding: 20px;">Cargando bloques de cita disponibles...</div>';
    
    try {
        const response = await fetch(`/api/appointments/available?id_sede=${state.wizard.selectedBranch}&id_especialidad=${state.wizard.selectedSpecialty}`);
        const slots = await response.json();
        
        state.wizard.availableSlots = slots;
        container.innerHTML = '';
        
        if (slots.length === 0) {
            container.innerHTML = `
                <div style="grid-column: 1/-1; text-align:center; padding: 20px;">
                    <p style="font-size:18px; font-weight:700; margin-bottom:0;">No hay turnos disponibles para esta sede y especialidad en el día de hoy.</p>
                </div>
            `;
            document.getElementById('waitlist-registration-card').classList.remove('hidden');
            document.querySelector('input[name="waitlist-type"][value="FechaCercana"]').checked = true;
            document.getElementById('waitlist-start-date').value = '';
            document.getElementById('waitlist-end-date').value = '';
            if (typeof toggleWaitlistRangeFields === 'function') {
                toggleWaitlistRangeFields();
            }
            speakText('No se encontraron horarios libres. Si lo deseas, puedes registrarte en la lista de espera completando el formulario que aparece abajo.');
            return;
        }
        
        document.getElementById('waitlist-registration-card').classList.add('hidden');
        
        slots.forEach((slot, idx) => {
            const card = document.createElement('div');
            card.className = 'option-card';
            card.onclick = () => selectSlot(slot.id_cita);
            
            card.innerHTML = `
                <div class="option-card-title">🩺 ${slot.doctor_nombre}</div>
                <div class="option-card-desc">📅 ${slot.fecha} | ⏰ ${slot.hora_inicio} - ${slot.hora_fin}</div>
                <div class="option-card-badge">Opción ${idx + 1}</div>
            `;
            container.appendChild(card);
        });
        
        if (state.speech.synthesisActive) {
            const textVoice = `Encontrados ${slots.length} turnos disponibles. Elige una opción diciendo el número de opción correspondiente.`;
            speakText(textVoice);
        }
        
    } catch (e) {
        container.innerHTML = '<div style="grid-column: 1/-1; text-align:center; color:red; padding:20px;">Error al obtener turnos del servidor.</div>';
    }
}

function toggleWaitlistRangeFields() {
    const waitlistType = document.querySelector('input[name="waitlist-type"]:checked').value;
    const rangeFields = document.getElementById('waitlist-range-fields');
    if (waitlistType === 'RangoEspecifico') {
        rangeFields.classList.remove('hidden');
    } else {
        rangeFields.classList.add('hidden');
    }
}

function formatDateString(str) {
    if (!str) return '';
    const parts = str.split('-');
    if (parts.length !== 3) return str;
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
}

async function registerWaitlistSubmit() {
    const pId = state.session.id_perfil_clinico;
    const waitlistType = document.querySelector('input[name="waitlist-type"]:checked').value;
    
    let rango_inicio = null;
    let rango_fin = null;
    
    if (waitlistType === 'RangoEspecifico') {
        const startInput = document.getElementById('waitlist-start-date').value;
        const endInput = document.getElementById('waitlist-end-date').value;
        
        if (!startInput || !endInput) {
            showToast('Por favor seleccione las fechas de inicio y fin para el rango deseado.', 'error');
            speakText('Por favor seleccione las fechas de inicio y fin para el rango deseado.');
            return;
        }
        
        rango_inicio = startInput;
        rango_fin = endInput;
    }
    
    try {
        const response = await fetch('/api/waitlist/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id_paciente: pId,
                id_especialidad: state.wizard.selectedSpecialty,
                id_sede: state.wizard.selectedBranch,
                tipo_cola: waitlistType,
                rango_inicio: rango_inicio,
                rango_fin: rango_fin
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showToast(data.error || 'Error al unirse a la lista de espera.', 'error');
            speakText(`No se pudo procesar: ${data.error || ''}`);
            return;
        }
        
        speakText('Has sido agregado a la lista de espera del motor LEA de forma consistente.');
        showToast('Agregado con éxito a la lista de espera.', 'success');
        
        // Avanzar a confirmación alternativa
        state.wizard.step = 4;
        updateWizardUI();
        
        const specName = state.specialties.find(s => s.id_especialidad === state.wizard.selectedSpecialty).nombre;
        const branchName = state.branches.find(b => b.id_sede === state.wizard.selectedBranch).nombre;
        
        let confirmText = `Se registró con éxito tu solicitud en la <strong>Lista de Espera Automática (LEA)</strong> para la especialidad <strong>${specName}</strong> en la sede <strong>${branchName}</strong>.<br>`;
        if (waitlistType === 'RangoEspecifico') {
            confirmText += `Buscando citas disponibles entre el <strong>${formatDateString(rango_inicio)}</strong> y el <strong>${formatDateString(rango_fin)}</strong>. `;
        } else {
            confirmText += `Asignación automática por orden de llegada (Fecha más cercana). `;
        }
        confirmText += `Recibirás una notificación por mensaje de texto (SMS) en cuanto un turno quede disponible y se te asigne automáticamente.`;
        
        document.getElementById('wizard-confirm-text').innerHTML = confirmText;
        
        await refreshPatientSidebarLists();
        
    } catch (e) {
        showToast('Fallo al conectar con el servidor LEA.', 'error');
    }
}

function cancelAppointmentFromPatient(id_cita) {
    if (!confirm('¿Estás seguro de que deseas cancelar esta cita?')) return;
    
    executeCancellationAPI(id_cita, 'Paciente', state.session.id_perfil_clinico);
}

async function executeCancellationAPI(id_cita, rol, identificador) {
    try {
        const response = await fetch('/api/appointments/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id_cita: id_cita,
                realizado_por: rol,
                usuario_identificador: identificador
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showToast(data.error || 'Error al cancelar la cita.', 'error');
            speakText(`Error al cancelar: ${data.error || ''}`);
            return;
        }
        
        showToast(data.message, 'success');
        speakText('Cita cancelada correctamente. El slot ha sido liberado.');
        
        // Recargar datos
        if (state.activeView === 'patient-view') {
            await refreshPatientSidebarLists();
        } else if (state.activeView === 'recep-view') {
            await refreshReceptionistTodayAppointments();
        }
        
    } catch (e) {
        showToast('Error al enviar solicitud de cancelación.', 'error');
    }
}

// Navegación de Pasos
function nextWizardStep() {
    if (state.wizard.step === 1 && !state.wizard.selectedSpecialty) {
        speakText('Por favor, selecciona una especialidad antes de avanzar.');
        return;
    }
    if (state.wizard.step === 2 && !state.wizard.selectedBranch) {
        speakText('Por favor, selecciona una sede clínica antes de avanzar.');
        return;
    }
    
    if (state.wizard.step < 3) {
        state.wizard.step++;
        updateWizardUI();
        
        if (state.wizard.step === 3) {
            loadWizardSlots();
        } else {
            announceWizardStep();
        }
    }
}

function prevWizardStep() {
    if (state.wizard.step > 1 && state.wizard.step < 4) {
        state.wizard.step--;
        updateWizardUI();
        announceWizardStep();
    }
}

function restartWizard() {
    state.wizard.step = 1;
    state.wizard.selectedSpecialty = null;
    state.wizard.selectedCity = null;
    state.wizard.selectedBranch = null;
    state.wizard.selectedSlot = null;
    state.wizard.availableSlots = [];
    
    // Ocultar tarjeta de lista de espera por defecto
    const wlCard = document.getElementById('waitlist-registration-card');
    if (wlCard) wlCard.classList.add('hidden');
    
    updateWizardUI();
    renderSpecialtiesGrid();
    renderBranchesGrid();
    announceWizardStep();
}

function updateWizardUI() {
    // Ocultar todos los subpaneles
    document.querySelectorAll('.wizard-step-panel').forEach(panel => {
        panel.classList.add('hidden');
    });
    
    // Mostrar el subpanel correspondiente
    document.getElementById(`wizard-step-${state.wizard.step}`).classList.remove('hidden');
    
    // Actualizar barra de indicadores
    document.querySelectorAll('.step-indicator').forEach(ind => {
        ind.classList.remove('active');
    });
    
    if (state.wizard.step <= 4) {
        const ind = document.getElementById(`step-ind-${state.wizard.step}`);
        if (ind) ind.classList.add('active');
    }
}

function announceWizardStep() {
    if (state.wizard.step === 1) {
        speakText('Paso uno. Selecciona la especialidad médica tocando una de las opciones en pantalla.');
    } else if (state.wizard.step === 2) {
        speakText('Paso dos. Selecciona la sede clínica de tu preferencia.');
    } else if (state.wizard.step === 3) {
        speakText('Paso tres. Elige el horario conveniente con el doctor de tu preferencia.');
    }
}

// 7. PORTAL DE LA RECEPCIONISTA (CHECK-IN Y HERRAMIENTAS ADM)
async function loadReceptionistDashboard() {
    // Inicializar catálogos
    try {
        const [branchesRes, doctorsRes, historyRes] = await Promise.all([
            fetch('/api/branches'),
            fetch('/api/doctors'),
            fetch('/api/admin/massive-cancellations-history')
        ]);
        
        state.branches = await branchesRes.json();
        state.doctors = await doctorsRes.json();
        const massiveHistory = await historyRes.json();
        
        populateReceptionistSelects();
        renderMassiveCancellationsHistory(massiveHistory);
        
        // Cargar citas de hoy
        await refreshReceptionistTodayAppointments();
        
        // Programar autorefresco cada 15 segundos para Check-in reactivo
        state.receptionist.refreshInterval = setInterval(refreshReceptionistTodayAppointments, 15000);
        
    } catch (e) {
        showToast('Error al inicializar panel de recepción.', 'error');
    }
}

function populateReceptionistSelects() {
    // Sede de Destino traslado
    const destSelect = document.getElementById('change-branch-destination-id');
    destSelect.innerHTML = '<option value="">-- Seleccionar sede --</option>';
    
    // Sede física cancelación masiva
    const massBranchSelect = document.getElementById('massive-cancel-branch-id');
    massBranchSelect.innerHTML = '<option value="">-- Todas las sedes --</option>';
    
    state.branches.forEach(b => {
        const opt = `<option value="${b.id_sede}">${b.nombre} (${b.ciudad})</option>`;
        destSelect.insertAdjacentHTML('beforeend', opt);
        massBranchSelect.insertAdjacentHTML('beforeend', opt);
    });
    
    // Médicos cancelación masiva
    const massDocSelect = document.getElementById('massive-cancel-doctor-id');
    massDocSelect.innerHTML = '<option value="">-- Todos los médicos --</option>';
    state.doctors.forEach(d => {
        const opt = `<option value="${d.id_medico}">${d.nombre_completo} (${d.especialidad_nombre})</option>`;
        massDocSelect.insertAdjacentHTML('beforeend', opt);
    });
}

async function refreshReceptionistTodayAppointments() {
    try {
        // Obtenemos las citas filtradas por la sede de la recepcionista asignada (si la tiene)
        const branchParam = state.session.id_sede ? `?id_sede=${state.session.id_sede}` : '';
        const response = await fetch(`/api/receptionist/appointments${branchParam}`);
        const appointments = await response.json();
        
        renderReceptionistAppointmentsTable(appointments);
    } catch (e) {
        console.error('Error al actualizar las citas en recepción:', e);
    }
}

function renderReceptionistAppointmentsTable(list) {
    const tbody = document.getElementById('recep-appointments-tbody');
    tbody.innerHTML = '';
    
    if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">No se encontraron citas registradas para el día de hoy.</td></tr>';
        return;
    }
    
    list.forEach(apt => {
        const row = document.createElement('tr');
        
        let actionButtons = '';
        if (apt.estado === 'Agendada') {
            actionButtons = `
                <button class="btn btn-primary" style="min-height:36px; height:36px; padding:2px 8px; font-size:12px; margin-right:6px;" onclick="admitPatient('${apt.id_cita}')">[✔ Admitir / Llegó]</button>
                <button class="btn btn-danger" style="min-height:36px; height:36px; padding:2px 8px; font-size:12px;" onclick="cancelAppointmentFromRecep('${apt.id_cita}')">[❌ Liberar]</button>
            `;
        } else if (apt.estado === 'Confirmada') {
            actionButtons = '<span style="color:var(--success); font-weight:700;">Admitido (En Sala)</span>';
        } else {
            actionButtons = `<span style="color:var(--text-secondary);">${apt.estado}</span>`;
        }
        
        row.innerHTML = `
            <td><strong>${apt.hora}</strong></td>
            <td>
                <strong>${apt.paciente_nombre}</strong><br>
                <span style="font-size:11px; color:var(--text-secondary);">DNI: ${apt.paciente_dni}</span>
            </td>
            <td>${apt.doctor_nombre}</td>
            <td>${apt.sede_nombre}</td>
            <td><strong class="badge badge-${apt.estado.toLowerCase()}">${apt.estado}</strong></td>
            <td>${actionButtons}</td>
        `;
        tbody.appendChild(row);
    });
}

// Búsqueda autocomplete MS Teams-Style
async function onSearchPatientInput() {
    const input = document.getElementById('recep-search-input');
    const dropdown = document.getElementById('recep-search-results');
    const val = input.value.trim();
    
    if (val.length < 2) {
        dropdown.innerHTML = '';
        dropdown.classList.add('hidden');
        return;
    }
    
    try {
        const response = await fetch(`/api/patients/search?query=${encodeURIComponent(val)}`);
        const patients = await response.json();
        
        dropdown.innerHTML = '';
        
        if (patients.length === 0) {
            dropdown.innerHTML = '<div class="autocomplete-item" style="cursor:default;">Ningún paciente coincide.</div>';
            dropdown.classList.remove('hidden');
            return;
        }
        
        patients.forEach(p => {
            const item = document.createElement('div');
            item.className = 'autocomplete-item';
            item.onclick = () => selectPatientFromSearch(p);
            
            item.innerHTML = `
                <span class="autocomplete-item-name">${p.nombre_completo}</span>
                <span class="autocomplete-item-dni">DNI: ${p.dni} | Tel: ${p.telefono}</span>
            `;
            dropdown.appendChild(item);
        });
        
        dropdown.classList.remove('hidden');
        
    } catch (e) {
        console.error('Error al buscar paciente:', e);
    }
}

function selectPatientFromSearch(p) {
    const input = document.getElementById('recep-search-input');
    const dropdown = document.getElementById('recep-search-results');
    
    input.value = `${p.nombre_completo} (DNI: ${p.dni})`;
    dropdown.innerHTML = '';
    dropdown.classList.add('hidden');
    
    showToast(`Paciente seleccionado: ${p.nombre_completo}`, 'success');
}

// Admisión física
async function admitPatient(id_cita) {
    try {
        const response = await fetch('/api/appointments/check-in', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id_cita: id_cita,
                usuario_identificador: state.session.username
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showToast(data.error || 'Error al admitir al paciente.', 'error');
            return;
        }
        
        showToast(data.message, 'success');
        await refreshReceptionistTodayAppointments();
        
    } catch (e) {
        showToast('Error de comunicación con el servidor.', 'error');
    }
}

function cancelAppointmentFromRecep(id_cita) {
    if (!confirm('¿Desea cancelar y liberar esta cita médica?')) return;
    executeCancellationAPI(id_cita, 'Recepcionista', state.session.username);
}

// Cambio de sede
async function changeBranchSubmit() {
    const citaInput = document.getElementById('change-branch-appointment-id');
    const destSelect = document.getElementById('change-branch-destination-id');
    
    const id_cita = citaInput.value.trim();
    const id_sede_destino = destSelect.value;
    
    if (!id_cita || !id_sede_destino) {
        showToast('Por favor ingrese el ID de la cita y la sede de destino.', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/appointments/change-branch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id_cita,
                id_sede_destino,
                realizado_por: 'Recepcionista',
                usuario_identificador: state.session.username
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showToast(data.error || 'Error al cambiar sede.', 'error');
            return;
        }
        
        showToast(data.message, 'success');
        citaInput.value = '';
        destSelect.value = '';
        await refreshReceptionistTodayAppointments();
        
    } catch (e) {
        showToast('Fallo al realizar cambio de sede.', 'error');
    }
}

// Cancelación masiva
async function massiveCancellationSubmit() {
    const branchSelect = document.getElementById('massive-cancel-branch-id');
    const docSelect = document.getElementById('massive-cancel-doctor-id');
    const rescheduleCheck = document.getElementById('massive-cancel-reschedule');
    const reportBox = document.getElementById('massive-cancel-report');
    
    const id_sede = branchSelect.value || null;
    const id_medico = docSelect.value || null;
    const auto_reschedule = rescheduleCheck.checked;
    
    if (!id_sede && !id_medico) {
        showToast('Debe seleccionar al menos una Sede o un Médico para la cancelación masiva.', 'error');
        return;
    }
    
    if (!confirm('⚠️ ¡ATENCIÓN! Se cancelarán todas las citas futuras del criterio seleccionado de forma irreversible. ¿Desea continuar?')) return;
    
    try {
        const response = await fetch('/api/appointments/massive-cancellation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id_sede,
                id_medico,
                auto_reschedule,
                realizado_por: 'Recepcionista',
                id_usuario_ejecutor: state.session.id_usuario
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showToast(data.error || 'Error al ejecutar cancelación masiva.', 'error');
            return;
        }
        
        showToast(data.message, 'success');
        
        // Renderizar reporte de auditoría devuelto
        reportBox.innerHTML = `
            <strong>Cancelación Masiva Ejecutada:</strong><br>
            🎯 Citas afectadas: ${data.cantidad_afectadas}<br>
            📂 Reporte guardado localmente en:<br>
            <code>${data.reporte_path}</code>
        `;
        reportBox.classList.remove('hidden');
        
        // Recargar historial
        const historyRes = await fetch('/api/admin/massive-cancellations-history');
        const massiveHistory = await historyRes.json();
        renderMassiveCancellationsHistory(massiveHistory);
        
        // Limpiar selects
        branchSelect.value = '';
        docSelect.value = '';
        
    } catch (e) {
        showToast('Fallo crítico al ejecutar contingencia de cancelación masiva.', 'error');
    }
}

function renderMassiveCancellationsHistory(list) {
    const container = document.getElementById('massive-cancellations-history-list');
    container.innerHTML = '';
    
    if (list.length === 0) {
        container.innerHTML = '<div class="sidebar-help">Sin registros históricos de cancelaciones masivas.</div>';
        return;
    }
    
    list.forEach(item => {
        const div = document.createElement('div');
        div.className = 'list-item';
        div.innerHTML = `
            <div class="list-item-title">⚠️ Cantidad Citas: ${item.cantidad_canceladas}</div>
            <div class="list-item-meta">
                🏢 Sede: ${item.sede_nombre}<br>
                🩺 Médico: ${item.doctor_nombre}<br>
                🔄 Auto-reprogramado: ${item.auto_reschedule ? 'SÍ (LEA)' : 'NO'}<br>
                📅 Ejecutado: ${item.fecha_ejecucion} por <strong>${item.ejecutado_por}</strong>
            </div>
        `;
        container.appendChild(div);
    });
}

// 8. SALA DE ESPERA DEL MÉDICO
async function loadMedicoDashboard() {
    state.medico.selectedAppointment = null;
    document.getElementById('evolution-patient-name').value = 'Ninguno seleccionado';
    document.getElementById('evolution-appointment-id').value = '';
    document.getElementById('evolution-clinical-notes').value = '';
    document.getElementById('btn-complete-evolution').disabled = true;
    
    // Cargar sala de espera
    await refreshDoctorWaitingRoom();
    
    // Autorefresco de sala de espera del médico cada 10 segundos
    state.medico.waitingRoomInterval = setInterval(refreshDoctorWaitingRoom, 10000);
}

async function refreshDoctorWaitingRoom() {
    if (!state.session || !state.session.id_perfil_clinico) return;
    
    try {
        const response = await fetch(`/api/doctor/waiting-room?id_medico=${state.session.id_perfil_clinico}`);
        const waitingPatients = await response.json();
        
        renderDoctorWaitingRoom(waitingPatients);
    } catch (e) {
        console.error('Error al actualizar sala de espera del médico:', e);
    }
}

function renderDoctorWaitingRoom(list) {
    const container = document.getElementById('medico-waiting-patients-list');
    container.innerHTML = '';
    
    if (list.length === 0) {
        container.innerHTML = '<div class="subtitle" style="text-align:center; padding: 20px;">No hay pacientes en sala de espera para el día de hoy.</div>';
        return;
    }
    
    list.forEach(apt => {
        const card = document.createElement('div');
        card.className = `waiting-patient-card ${state.medico.selectedAppointment === apt.id_cita ? 'selected' : ''}`;
        card.onclick = () => selectPatientForEvolution(apt);
        
        card.innerHTML = `
            <div class="patient-info">
                <span class="patient-name">${apt.paciente_nombre}</span>
                <span style="font-size:12px; color:var(--text-secondary);">DNI: ${apt.paciente_dni}</span>
            </div>
            <div class="patient-time-badge">⏰ ${apt.hora}</div>
        `;
        container.appendChild(card);
    });
}

function selectPatientForEvolution(apt) {
    state.medico.selectedAppointment = apt.id_cita;
    
    document.getElementById('evolution-patient-name').value = `${apt.paciente_nombre} (DNI: ${apt.paciente_dni})`;
    document.getElementById('evolution-appointment-id').value = apt.id_cita;
    document.getElementById('btn-complete-evolution').disabled = false;
    
    // Volver a renderizar lista para aplicar la clase .selected
    refreshDoctorWaitingRoom();
    
    showToast(`Paciente en consulta: ${apt.paciente_nombre}`, 'success');
}

async function completeEvolutionSubmit() {
    const id_cita = document.getElementById('evolution-appointment-id').value;
    const nota_clinica = document.getElementById('evolution-clinical-notes').value.trim();
    
    if (!id_cita) return;
    
    if (!nota_clinica) {
        showToast('Debe ingresar las notas clínicas del diagnóstico antes de finalizar la consulta.', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/doctor/complete-appointment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id_cita,
                realizado_por: 'Medico',
                usuario_identificador: state.session.username,
                nota_clinica
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showToast(data.error || 'Error al completar consulta.', 'error');
            return;
        }
        
        showToast(data.message, 'success');
        
        // Limpiar formulario de evolución
        document.getElementById('evolution-patient-name').value = 'Ninguno seleccionado';
        document.getElementById('evolution-appointment-id').value = '';
        document.getElementById('evolution-clinical-notes').value = '';
        document.getElementById('btn-complete-evolution').disabled = true;
        state.medico.selectedAppointment = null;
        
        // Recargar sala de espera
        await refreshDoctorWaitingRoom();
        
    } catch (e) {
        showToast('Fallo al conectar con el servidor para guardar historial.', 'error');
    }
}

// 9. PANEL DEL ADMINISTRADOR (CREACIÓN UNIFICADA Y DELEGACIÓN)
async function loadAdminDashboard() {
    try {
        const [branchesRes, specialtiesRes, receptionistsRes] = await Promise.all([
            fetch('/api/branches'),
            fetch('/api/specialties'),
            fetch('/api/receptionists')
        ]);
        
        state.branches = await branchesRes.json();
        state.specialties = await specialtiesRes.json();
        state.receptionists = await receptionistsRes.json();
        
        populateAdminSelects();
    } catch (e) {
        showToast('Error al inicializar panel administrativo.', 'error');
    }
}

function populateAdminSelects() {
    // Sede creación unificada
    const branchSelect = document.getElementById('admin-user-branch');
    branchSelect.innerHTML = '<option value="">-- Seleccionar sede --</option>';
    
    state.branches.forEach(b => {
        branchSelect.insertAdjacentHTML('beforeend', `<option value="${b.id_sede}">${b.nombre} (${b.ciudad})</option>`);
    });
    
    // Especialidades creación médico
    const specSelect = document.getElementById('admin-doc-specialty');
    specSelect.innerHTML = '<option value="">-- Seleccionar especialidad --</option>';
    state.specialties.forEach(s => {
        specSelect.insertAdjacentHTML('beforeend', `<option value="${s.id_especialidad}">${s.nombre}</option>`);
    });
    
    // Recepcionistas para delegación
    const recepSelect = document.getElementById('deleg-user-id');
    recepSelect.innerHTML = '<option value="">-- Seleccionar Recepcionista --</option>';
    state.receptionists.forEach(r => {
        recepSelect.insertAdjacentHTML('beforeend', `<option value="${r.id_usuario}">${r.username} (${r.email})</option>`);
    });
}

function onAdminUserRolChange() {
    const rol = document.getElementById('admin-user-rol').value;
    const docFields = document.getElementById('admin-doctor-fields');
    
    if (rol === 'Medico') {
        docFields.classList.remove('hidden');
    } else {
        docFields.classList.add('hidden');
    }
}

async function createUserSubmit() {
    const username = document.getElementById('admin-user-username').value.trim();
    const email = document.getElementById('admin-user-email').value.trim();
    const password = document.getElementById('admin-user-password').value.trim();
    const rol = document.getElementById('admin-user-rol').value;
    const id_sede = document.getElementById('admin-user-branch').value || null;
    
    if (!username || !email || !password || !rol) {
        showToast('Por favor complete todos los datos obligatorios del usuario.', 'error');
        return;
    }
    
    const bodyData = {
        username,
        email,
        password,
        rol,
        id_sede
    };
    
    // Añadir datos de médicos si aplica
    if (rol === 'Medico') {
        const numero_licencia = document.getElementById('admin-doc-licencia').value.trim();
        const nombre_completo = document.getElementById('admin-doc-nombre').value.trim();
        const id_especialidad = document.getElementById('admin-doc-specialty').value;
        const duracion_defecto = document.getElementById('admin-doc-duration').value;
        
        if (!numero_licencia || !nombre_completo || !id_especialidad) {
            showToast('Por favor complete los datos obligatorios de la licencia y nombre del médico.', 'error');
            return;
        }
        
        bodyData.numero_licencia = numero_licencia;
        bodyData.nombre_completo = nombre_completo;
        bodyData.id_especialidad = id_especialidad;
        bodyData.duracion_defecto = duracion_defecto;
    }
    
    try {
        const response = await fetch('/api/admin/create-user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(bodyData)
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showToast(data.error || 'Error al crear usuario.', 'error');
            return;
        }
        
        showToast(data.message, 'success');
        
        // Limpiar campos
        document.getElementById('admin-user-username').value = '';
        document.getElementById('admin-user-email').value = '';
        document.getElementById('admin-user-password').value = '';
        document.getElementById('admin-user-branch').value = '';
        
        if (rol === 'Medico') {
            document.getElementById('admin-doc-licencia').value = '';
            document.getElementById('admin-doc-nombre').value = '';
            document.getElementById('admin-doc-specialty').value = '';
            document.getElementById('admin-doctor-fields').classList.add('hidden');
            document.getElementById('admin-user-rol').value = 'Recepcionista';
        }
        
        // Recargar recepcionistas por si se creó uno nuevo
        const recepRes = await fetch('/api/receptionists');
        state.receptionists = await recepRes.json();
        populateAdminSelects();
        
    } catch (e) {
        showToast('Fallo de conexión al crear la cuenta.', 'error');
    }
}

async function delegatePermissionSubmit() {
    const id_usuario_receptor = document.getElementById('deleg-user-id').value;
    const permiso_nombre = document.getElementById('deleg-permission-name').value;
    const fecha_inicio = document.getElementById('deleg-start-date').value;
    const fecha_expiracion = document.getElementById('deleg-end-date').value || null;
    
    if (!id_usuario_receptor || !permiso_nombre || !fecha_inicio) {
        showToast('Por favor complete la recepcionista, el permiso y la fecha de inicio.', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/admin/delegate-permission', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id_usuario_receptor,
                permiso_nombre,
                fecha_inicio: new Date(fecha_inicio).toISOString(),
                fecha_expiracion: fecha_expiracion ? new Date(fecha_expiracion).toISOString() : null,
                creado_por: state.session.id_usuario
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showToast(data.error || 'Error al delegar el permiso.', 'error');
            return;
        }
        
        showToast(data.message, 'success');
        
        // Limpiar formulario
        document.getElementById('deleg-user-id').value = '';
        document.getElementById('deleg-start-date').value = '';
        document.getElementById('deleg-end-date').value = '';
        
    } catch (e) {
        showToast('Fallo en la comunicación de red para delegar permiso.', 'error');
    }
}

// 10. NOTIFICACIONES ACCESIBLES (TOASTS)
let toastTimeout;
function showToast(message, type = 'success') {
    const toast = document.getElementById('toast-notification');
    
    toast.innerText = message;
    toast.className = `toast toast-${type}`;
    toast.classList.remove('hidden');
    
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => {
        toast.classList.add('hidden');
    }, 4500);
}

// 11. GESTIÓN DE TEMAS VISUALES
function setTheme(themeName) {
    state.theme = themeName;
    document.body.className = `theme-${themeName}`;
    localStorage.setItem('sgcm-theme', themeName);
    
    // Actualizar botones del selector de temas
    document.querySelectorAll('.theme-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    const activeBtn = document.getElementById(`btn-theme-${themeName}`);
    if (activeBtn) activeBtn.classList.add('active');
}
