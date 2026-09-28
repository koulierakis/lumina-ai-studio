/**
 * storage.js - LocalStorage Management Module
 */

const STORAGE_KEYS = {
    FAVORITES: 'lumina_gps_favorites',
    SETTINGS: 'lumina_gps_settings'
};

export const StorageService = {
    getFavorites() {
        const data = localStorage.getItem(STORAGE_KEYS.FAVORITES);
        return data ? JSON.parse(data) : {
            home: null,
            work: null,
            custom: []
        };
    },

    saveFavorite(type, payload) {
        const favs = this.getFavorites();
        if (type === 'home' || type === 'work') {
            favs[type] = payload; // { name, lat, lon }
        } else {
            favs.custom.push(payload); // { id, name, lat, lon }
        }
        localStorage.setItem(STORAGE_KEYS.FAVORITES, JSON.stringify(favs));
        return favs;
    },

    removeCustomFavorite(id) {
        const favs = this.getFavorites();
        favs.custom = favs.custom.filter(f => f.id !== id);
        localStorage.setItem(STORAGE_KEYS.FAVORITES, JSON.stringify(favs));
        return favs;
    },

    getSettings() {
        const data = localStorage.getItem(STORAGE_KEYS.SETTINGS);
        return data ? JSON.parse(data) : {
            language: 'el-GR',
            speedLimit: 90,
            nightModeAuto: true
        };
    },

    saveSettings(settings) {
        localStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(settings));
    }
};
